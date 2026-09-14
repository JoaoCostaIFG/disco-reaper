"""
Tests for the Migration Verification feature (Verify Migration button).

Covers the verify_messages implementations in the Fluxer and Stoat platform
modules, the mapping-retrieval database helpers, and the bulk verification UI logic.
"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.base import MigrationContext
from src.core.database import MigrationDatabase
from src.fluxer.migrate_message import verify_messages as fluxer_verify, _extract_target_body as fluxer_extract
from src.stoat.migrate_message import verify_messages as stoat_verify, _extract_target_body as stoat_extract


def _msg(mid, content, msg_type, attachments=None, stickers=None, ts=1600000000, reference=None, forwarded=False):
    """Builds a discord.Message-like stand-in with only the fields verification reads."""
    return SimpleNamespace(
        id=mid,
        content=content,
        type=msg_type,
        attachments=attachments or [],
        stickers=stickers or [],
        embeds=[],
        mentions=[],
        role_mentions=[],
        channel_mentions=[],
        message_snapshots=None,
        reference=reference,
        flags=SimpleNamespace(forwarded=forwarded),
        author=SimpleNamespace(id=222, display_name="Alice"),
        created_at=SimpleNamespace(timestamp=lambda: float(ts)),
        channel=SimpleNamespace(id=100),
    )


def _fluxer_target(mid, content, attachments=None):
    return {"id": str(mid), "content": content, "attachments": attachments or [], "author": {"username": "Alice (discord)"}}


def _make_history(messages_by_channel):
    async def fetch(channel_id, **kwargs):
        for m in messages_by_channel.get(channel_id, []):
            yield m
    return MagicMock(side_effect=fetch)


@pytest.fixture
def verify_reader():
    reader = MagicMock()
    reader.threads = []
    reader.fetch_channels = AsyncMock(return_value=[])
    reader.get_active_threads = AsyncMock(return_value=[])
    reader.guild = SimpleNamespace(id=555, get_member=lambda uid: None, get_role=lambda rid: None, get_channel=lambda cid: None)
    return reader


def _make_context(reader, target_channel_id="tc1"):
    context = MagicMock(spec=MigrationContext)
    context.discord_reader = reader
    context.is_running = True
    context.config = MagicMock(anonymize_users=False)
    context.channel_names = {}
    context.fluxer_writer = MagicMock()
    context.fluxer_writer.community_id = "tc999"
    context.fluxer_writer.client = MagicMock()
    context.stoat_writer = MagicMock()
    context.stoat_writer.community_id = "tc999"
    context.stoat_writer.client = MagicMock()
    context.state = MagicMock()
    context.state.emoji_map = {}
    context.state.channel_map = {}
    context.state.get_target_message_id = MagicMock(side_effect=lambda ch, src: None)
    context.state.get_thread_message_id = MagicMock(side_effect=lambda ch, tid, src: None)
    context.state.get_all_message_mappings = MagicMock(return_value={})
    context.state.get_all_thread_message_mappings = MagicMock(return_value={})
    context.target_platform = "fluxer"
    return context


# --- Prefix extraction helpers ---

def test_extract_target_body_fluxer():
    content = "-# <t:1600000000:D>\n-# ⮫*forwarded*\n-# · Alice\n>>> Hello"
    body, ts = fluxer_extract(content)
    assert body == ">>> Hello"
    assert ts == 1600000000


def test_extract_target_body_fluxer_missing_prefix():
    body, ts = fluxer_extract("Hello")
    assert body == "Hello"
    assert ts is None


def test_extract_target_body_stoat():
    content = "###### <t:1600000000:D>\n##### ⮫*forwarded*\n> Hello"
    body, ts = stoat_extract(content)
    assert body == "> Hello"
    assert ts == 1600000000


def test_extract_target_body_preserves_user_subtext():
    # A user message that itself starts with subtext keeps it in the body
    body, ts = fluxer_extract("-# <t:1600000000:D>\n-# user line\nHello")
    assert body == "-# user line\nHello"


# --- Fluxer verify_messages ---

@pytest.mark.asyncio
async def test_verify_messages_fluxer_full_report(verify_reader):
    ctx = _make_context(verify_reader)
    DEFAULT = verify_reader.MESSAGE_TYPE_DEFAULT
    OTHER = verify_reader.MESSAGE_TYPE_RECIPIENT_ADD

    msgs = {
        100: [
            _msg(111, "Hello", DEFAULT),
            _msg(222, "Second", DEFAULT),
            _msg(333, "Third", DEFAULT),
            _msg(444, "Fourth", DEFAULT),
            _msg(555, "Fifth", DEFAULT, attachments=[SimpleNamespace(filename="a.png")]),
            _msg(666, "System thing", OTHER),   # non-migratable type
            _msg(777, "", DEFAULT),             # no content/files: never sent
        ],
        900: [
            _msg(901, "ThreadMsg", DEFAULT),
        ],
    }
    verify_reader.fetch_message_history = _make_history(msgs)
    verify_reader.threads = [SimpleNamespace(id=900, parent_id=100, name="mythread")]

    ts = 1600000000
    target_batch = [
        _fluxer_target(900001, f"-# <t:{ts}:D>\nHello"),
        _fluxer_target(900002, f"-# <t:{ts}:D>\nWRONG"),
        _fluxer_target(900005, f"-# <t:{ts}:D>\nFifth"),
        _fluxer_target(900901, f"-# <t:{ts}:D>\n> <<< THREAD: **mythread** >>>\nThreadMsg"),
        _fluxer_target(900888, "stray message"),
    ]
    ctx.fluxer_writer.client.get_messages = AsyncMock(side_effect=[target_batch, []])

    main_map = {"111": "900001", "222": "900002", "444": "900099", "555": "900005"}
    ctx.state.get_target_message_id.side_effect = lambda ch, src: main_map.get(src)
    ctx.state.get_thread_message_id.side_effect = lambda ch, tid, src: "900901" if src == "901" else None
    ctx.state.get_all_message_mappings.return_value = main_map
    ctx.state.get_all_thread_message_mappings.return_value = {"901": "900901"}

    progress = AsyncMock()
    result = await fluxer_verify(ctx, source_channel_id=100, target_channel_id="tc1", progress_callback=progress)

    assert result["scanned"] == 8
    assert result["skipped"] == 2
    assert result["checked"] == 6
    assert result["verified"] == 2          # 111 + thread 901
    assert result["missing_mapping"] == 1  # 333
    assert result["missing_on_target"] == 1 # 444
    assert result["content_mismatch"] == 1  # 222
    assert result["attachment_mismatch"] == 1  # 555
    assert result["extra_on_target"] == 1  # 900888
    assert result["target_messages"] == 5
    assert progress.await_count >= 1


@pytest.mark.asyncio
async def test_verify_messages_fluxer_reply_fallback_and_forward(verify_reader):
    ctx = _make_context(verify_reader)
    DEFAULT = verify_reader.MESSAGE_TYPE_DEFAULT

    # Reply whose target is unmapped -> migration prefixed `@Bob`; forwarded content gets ">>>" quoting
    ref_msg = _msg(112, "A forwarded reply", DEFAULT, reference=SimpleNamespace(message_id=999), forwarded=True)
    msgs = {100: [ref_msg]}
    verify_reader.fetch_message_history = _make_history(msgs)

    ts = 1600000000
    target_batch = [
        _fluxer_target(900012, f"-# <t:{ts}:D>\n-# ⮫*forwarded*\n`@Bob`\n>>> A forwarded reply"),
    ]
    ctx.fluxer_writer.client.get_messages = AsyncMock(side_effect=[target_batch, []])
    ctx.state.get_target_message_id.side_effect = lambda ch, src: "900012" if src == "112" else None
    ctx.state.get_all_message_mappings.return_value = {"112": "900012"}

    result = await fluxer_verify(ctx, source_channel_id=100, target_channel_id="tc1")

    assert result["verified"] == 1
    assert result["checked"] == 1
    assert result["content_mismatch"] == 0


@pytest.mark.asyncio
async def test_verify_messages_fluxer_end_of_thread_marker_not_extra(verify_reader):
    ctx = _make_context(verify_reader)
    DEFAULT = verify_reader.MESSAGE_TYPE_DEFAULT

    verify_reader.fetch_message_history = _make_history({100: [_msg(111, "Hello", DEFAULT)]})
    ts = 1600000000
    target_batch = [
        _fluxer_target(900001, f"-# <t:{ts}:D>\nHello"),
        _fluxer_target(900999, "> <<< END OF THREAD >>>"),  # marker: unmapped but legitimate
    ]
    ctx.fluxer_writer.client.get_messages = AsyncMock(side_effect=[target_batch, []])
    ctx.state.get_target_message_id.side_effect = lambda ch, src: "900001" if src == "111" else None
    ctx.state.get_all_message_mappings.return_value = {"111": "900001"}

    result = await fluxer_verify(ctx, source_channel_id=100, target_channel_id="tc1")

    assert result["verified"] == 1
    assert result["extra_on_target"] == 0


@pytest.mark.asyncio
async def test_verify_messages_fluxer_cancel_stops(verify_reader):
    ctx = _make_context(verify_reader)
    DEFAULT = verify_reader.MESSAGE_TYPE_DEFAULT

    async def fetch(channel_id, **kwargs):
        ctx.is_running = False  # simulate cancel before the first message
        yield _msg(111, "Hello", DEFAULT)

    verify_reader.fetch_message_history = MagicMock(side_effect=fetch)
    ctx.fluxer_writer.client.get_messages = AsyncMock(side_effect=[[], []])

    result = await fluxer_verify(ctx, source_channel_id=100, target_channel_id="tc1")
    assert result["checked"] == 0


# --- Stoat verify_messages ---

@pytest.fixture
def stoat_verify_context(verify_reader):
    ctx = _make_context(verify_reader)
    ctx.target_platform = "stoat"
    channel = MagicMock()
    channel.history = AsyncMock(side_effect=[[], []])
    ctx.stoat_writer.client.fetch_channel = AsyncMock(return_value=channel)
    return ctx, channel


@pytest.mark.asyncio
async def test_verify_messages_stoat_ok(stoat_verify_context):
    ctx, channel = stoat_verify_context
    DEFAULT = ctx.discord_reader.MESSAGE_TYPE_DEFAULT

    verify_reader = ctx.discord_reader
    verify_reader.fetch_message_history = _make_history({100: [_msg(111, "Hello", DEFAULT)]})

    ts = 1600000000
    tgt = SimpleNamespace(
        id="900001",
        content=f"###### <t:{ts}:D>\nHello",
        attachments=[],
        masquerade=SimpleNamespace(name="Alice (discord)"),
        author=None,
    )
    channel.history = AsyncMock(side_effect=[[tgt], []])
    ctx.state.get_target_message_id.side_effect = lambda ch, src: "900001" if src == "111" else None
    ctx.state.get_all_message_mappings.return_value = {"111": "900001"}

    result = await stoat_verify(ctx, source_channel_id=100, target_channel_id="tc1")

    assert result["verified"] == 1
    assert result["content_mismatch"] == 0
    assert result["extra_on_target"] == 0


@pytest.mark.asyncio
async def test_verify_messages_stoat_blocked_attachments(stoat_verify_context):
    """Attachment type blocked by Stoat appends a note — must count as attachment issue, not content mismatch."""
    ctx, channel = stoat_verify_context
    DEFAULT = ctx.discord_reader.MESSAGE_TYPE_DEFAULT

    ctx.discord_reader.fetch_message_history = _make_history({
        100: [_msg(111, "Hello", DEFAULT, attachments=[SimpleNamespace(filename="a.png")])]
    })

    ts = 1600000000
    note = "\n⚠ 1 attachment(s) (file type not allowed by stoat)\n- a.png"
    tgt = SimpleNamespace(
        id="900001",
        content=f"###### <t:{ts}:D>\nHello{note}",
        attachments=[],
        masquerade=None,
        author=None,
    )
    channel.history = AsyncMock(side_effect=[[tgt], []])
    ctx.state.get_target_message_id.side_effect = lambda ch, src: "900001" if src == "111" else None
    ctx.state.get_all_message_mappings.return_value = {"111": "900001"}

    result = await stoat_verify(ctx, source_channel_id=100, target_channel_id="tc1")

    assert result["content_mismatch"] == 0
    assert result["attachment_mismatch"] == 1
    assert "file type not allowed" in result["issues"][0]["detail"]


# --- Database helpers ---

def test_get_all_thread_message_mappings(tmp_path):
    db = MigrationDatabase(tmp_path / "m.db", platform="fluxer")
    db.set_message_mapping("tc1", "111", "900111")
    db.set_thread_message_mapping("tc1", "900", "901", "900901")
    db.set_thread_message_mapping("tc1", "900", "902", "900902")
    db.set_thread_message_mapping("tc2", "950", "951", "900951")

    # Fluxer columns have INTEGER affinity, so numeric IDs come back as ints
    assert db.get_all_message_mappings("tc1") == {111: 900111}
    assert db.get_all_thread_message_mappings("tc1") == {901: 900901, 902: 900902}
    assert db.get_all_thread_message_mappings("tc2") == {951: 900951}
    assert db.get_all_thread_message_mappings("tc-unknown") == {}


# --- UI logic ---

def _pane():
    from src.ui.shuttle_ops import OperationPane
    pane = OperationPane.__new__(OperationPane)
    pane.target_platform = "fluxer"
    return pane


def _zero_result(**overrides):
    result = {
        "scanned": 3, "checked": 3, "verified": 3, "skipped": 0,
        "missing_mapping": 0, "missing_on_target": 0, "content_mismatch": 0,
        "attachment_mismatch": 0, "extra_on_target": 0, "target_messages": 3,
        "issues": [],
    }
    result.update(overrides)
    return result


@pytest.mark.asyncio
async def test_bulk_verify_all_channels():
    pane = _pane()

    engine = MagicMock()
    engine.config.fluxer_server_id = "guild-1"
    engine.writer.validate = AsyncMock(return_value={"community_name": "Target"})
    engine.ensure_state_initialized = MagicMock()
    engine.is_running = True
    engine.state.get_target_channel_id.side_effect = lambda src: {"1": "t1"}.get(src)
    pane.engine = engine

    migrate_mod = MagicMock()
    migrate_mod.verify_messages = AsyncMock(return_value=_zero_result())

    modal = MagicMock()
    d_channels = [SimpleNamespace(id=1, name="general"), SimpleNamespace(id=2, name="random")]

    with patch("src.ui.shuttle_ops.log_audit_event", AsyncMock()):
        await pane._logic_verify_all_channels(modal, d_channels, "Fluxer", migrate_mod)

    # Only the mapped channel is verified; the unmapped one is skipped
    assert migrate_mod.verify_messages.await_count == 1
    assert migrate_mod.verify_messages.await_args.kwargs["source_channel_id"] == 1
    assert migrate_mod.verify_messages.await_args.kwargs["target_channel_id"] == "t1"

    writes = [c.args[0] for c in modal.write.call_args_list if c.args]
    assert any("no target mapping" in w for w in writes)
    assert any("OK (3 messages verified)" in w for w in writes)
    modal.phase_report.assert_called_once()


@pytest.mark.asyncio
async def test_bulk_verify_reports_channel_issues():
    pane = _pane()

    engine = MagicMock()
    engine.config.fluxer_server_id = "guild-1"
    engine.writer.validate = AsyncMock(return_value={"community_name": "Target"})
    engine.ensure_state_initialized = MagicMock()
    engine.is_running = True
    engine.state.get_target_channel_id.side_effect = lambda src: {"1": "t1"}.get(src)
    pane.engine = engine

    migrate_mod = MagicMock()
    migrate_mod.verify_messages = AsyncMock(return_value=_zero_result(
        verified=2, missing_mapping=1, issues=[{"kind": "missing_mapping", "source_id": "333", "author": "Alice", "detail": "never migrated", "content": "Third"}]
    ))

    modal = MagicMock()
    d_channels = [SimpleNamespace(id=1, name="general")]

    with patch("src.ui.shuttle_ops.log_audit_event", AsyncMock()):
        await pane._logic_verify_all_channels(modal, d_channels, "Fluxer", migrate_mod)

    writes = [c.args[0] for c in modal.write.call_args_list if c.args]
    assert any("1 issue(s)" in w for w in writes)
    assert any("Channels with issues: [red]1[/red]" in w for w in writes)


def test_write_verify_result_renders_issues():
    pane = _pane()
    modal = MagicMock()

    result = _zero_result(
        verified=2, content_mismatch=1,
        issues=[{"kind": "content_mismatch", "source_id": "222", "author": "Alice", "detail": "Content differs", "content": "Second"}],
    )
    issues = pane._write_verify_result(modal, SimpleNamespace(name="general"), {"name": "general"}, "Fluxer", result)

    assert issues == 1
    writes = [c.args[0] for c in modal.write.call_args_list if c.args]
    assert any("Verified OK: [green]2[/green] of 3 checked" in w for w in writes)
    assert any("CONTENT MISMATCH" in w for w in writes)


def test_write_verify_result_all_ok():
    pane = _pane()
    modal = MagicMock()

    issues = pane._write_verify_result(modal, SimpleNamespace(name="general"), {"name": "general"}, "Fluxer", _zero_result())

    assert issues == 0
    writes = [c.args[0] for c in modal.write.call_args_list if c.args]
    assert any("no issues found" in w for w in writes)
