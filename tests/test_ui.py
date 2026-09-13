import pytest
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from textual.app import App
from src.ui.main_app import ReaperApp, ConfigSelectionScreen, ConfigScreen
from src.ui.mode_screen import ModeScreen
from src.core.configuration import AppConfig

import os
from textual.widgets import ListItem, ListView, Input, Button, Label
import time



@pytest.fixture
def mock_configs(tmp_path, log):
    reaper_dir = tmp_path / "ReaperFiles-TestConfig"
    reaper_dir.mkdir()
    (reaper_dir / "reaper_config.yaml").write_text("discord_bot_token: 'fake'\ndiscord_server_id: '123'\ntool_mode: 'backup_only'")
    
    autotest_dir = tmp_path / "ReaperFiles-AutoTest"
    autotest_dir.mkdir()
    (autotest_dir / "reaper_config.yaml").write_text("discord_bot_token: 'fake'\ndiscord_server_id: '123'\ntool_mode: 'backup_transfer'")
    
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    log(f"CWD changed to: {tmp_path}")
    yield tmp_path
    os.chdir(old_cwd)

async def wait_for_screen(app, screen_class, timeout=5.0):
    import time
    start = time.time()
    while time.time() - start < timeout:
        if isinstance(app.screen, screen_class):
            return True
        await asyncio.sleep(0.1)
    return False

@pytest.mark.asyncio
async def test_ui_minimal_launch(mock_configs, log):
    """Verify app launch and screen transition to ModeScreen."""
    log("Running test_ui_minimal_launch")
    try:
        # Reverting to AsyncMock to avoid WorkerError. 
        # RuntimeWarnings are now handled globally in conftest.py.
        with patch("src.ui.main_app.ConfigSelectionScreen.check_updates", AsyncMock()):
            app = ReaperApp()
            async with app.run_test() as pilot:
                await wait_for_screen(app, ConfigSelectionScreen)
                await pilot.click(ListItem)
                await wait_for_screen(app, ModeScreen)
                assert isinstance(app.screen, ModeScreen)
                log("test_ui_minimal_launch PASSED")
    except Exception as e:
        log(f"test_ui_minimal_launch FAILED: {e}")
        raise

@pytest.mark.asyncio
async def test_ui_config_wizard_save(mock_configs, log):
    """Verify configuration editing and saving."""
    log("Running test_ui_config_wizard_save")
    try:
        with patch("src.ui.main_app.ConfigSelectionScreen.check_updates", AsyncMock()):
            app = ReaperApp()
            async with app.run_test() as pilot:
                await wait_for_screen(app, ConfigSelectionScreen)
                await pilot.click(ListItem)
                await wait_for_screen(app, ModeScreen)
                await pilot.click("#btn_config")
                await wait_for_screen(app, ConfigScreen)
                
                screen = app.screen
                inp = screen.query_one("#inp_discord_token", Input)
                inp.value = "new_fake_token"
                
                with patch("src.ui.main_app.save_config") as mock_save:
                    await pilot.click("#btn_save")
                    await pilot.pause(0.2)
                    assert mock_save.called
                    log("test_ui_config_wizard_save PASSED")
    except Exception as e:
        log(f"test_ui_config_wizard_save FAILED: {e}")
        raise

@pytest.mark.asyncio
async def test_ui_operation_trigger(mock_configs, log):
    """Verify that an operation can be triggered."""
    log("Running test_ui_operation_trigger")
    from src.ui.shuttle_ops import OperationPane
    from src.ui.modals import ChannelPickerScreen, ProgressScreen
    try:
        with patch("src.ui.main_app.ConfigSelectionScreen.check_updates", AsyncMock()):
            # run_validate is decorated with @work in shuttle_ops.py, so it MUST be a coroutine (AsyncMock)
            with patch.object(OperationPane, "run_validate", AsyncMock()):
                app = ReaperApp()
                async with app.run_test() as pilot:
                    await wait_for_screen(app, ConfigSelectionScreen)
                    await pilot.click(ListItem)
                    await wait_for_screen(app, ModeScreen)
                    
                    pane = app.screen.query_one(OperationPane)
                    pane.tokens_valid = True
                    pane.src_channels = [{"id": 1, "name": "t"}]
                    pane.src_cat_map = {None: "D"}
                    pane.tgt_channels = [{"id": 2, "name": "t"}]
                    pane.tgt_cat_map = {None: "D"}
                    pane.all_tgt_channels = pane.tgt_channels
                    
                    btn = pane.query_one("#op_backup_msgs", Button)
                    btn.disabled = False
                    await pilot.pause(0.2)
                    btn.focus()
                    await pilot.press("enter")
                    
                    await wait_for_screen(app, (ChannelPickerScreen, ProgressScreen))
                    assert isinstance(app.screen, (ChannelPickerScreen, ProgressScreen))
                    log("test_ui_operation_trigger PASSED")
    except Exception as e:
        log(f"test_ui_operation_trigger FAILED: {e}")
        raise

@pytest.mark.asyncio
async def test_ui_autotest_button(mock_configs, log):
    """Verify visibility and trigger of the AUTO TEST button."""
    log("Running test_ui_autotest_button")
    from src.ui.shuttle_ops import OperationPane
    try:
        with patch("src.ui.main_app.ConfigSelectionScreen.check_updates", AsyncMock()):
            with patch.object(OperationPane, "run_validate", AsyncMock()):
                app = ReaperApp()
                async with app.run_test() as pilot:
                    await wait_for_screen(app, ConfigSelectionScreen)
                    # Find the AutoTest item in the list
                    lv = app.screen.query_one(ListView)
                    autotest_index = -1
                    for idx, item in enumerate(lv.children):
                        if item.name == "AutoTest":
                            autotest_index = idx
                            break
                    
                    assert autotest_index != -1, "AutoTest profile not found in ListView"
                    target_item = lv.children[autotest_index]
                    await pilot.click(target_item)
                    assert await wait_for_screen(app, ModeScreen), "Timed out waiting for ModeScreen"
                    
                    # Verify button is present
                    pane = app.screen.query_one(OperationPane)
                    btn = pane.query_one("#op_autotest", Button)
                    assert btn.display is True
                    assert "AUTO TEST" in str(btn.label)
                    
                    # Mock the sequence and trigger it
                    with patch.object(OperationPane, "run_autotest_sequence", AsyncMock()) as mock_seq:
                        btn.disabled = False
                        await pilot.pause(0.1)
                        btn.focus()
                        await pilot.press("enter")
                        await pilot.pause(0.1)
                        assert mock_seq.called
                        log("test_ui_autotest_button PASSED")
    except Exception as e:
        log(f"test_ui_autotest_button FAILED: {e}")
        raise


@pytest.mark.asyncio
async def test_channel_picker_migrate_all_button(mock_configs, log):
    """Verify the Migrate All Channels button dismisses the picker with 'migrate_all'."""
    from src.ui.modals import ChannelPickerScreen
    try:
        src_ch = type("Ch", (), {"id": 1, "name": "general", "category_id": None})()
        tgt_ch = {"id": "t1", "name": "general", "type": 0, "parent_id": None}

        class PickerApp(App):
            def compose(self):
                yield Label("base")

        picked = []
        app = PickerApp()
        async with app.run_test() as pilot:
            app.push_screen(ChannelPickerScreen([src_ch], {None: "D"}, [tgt_ch], {None: "D"}, "Fluxer"), picked.append)
            assert await wait_for_screen(app, ChannelPickerScreen)

            screen = app.screen
            btn = None
            start = time.time()
            while time.time() - start < 5.0:
                try:
                    btn = screen.query_one("#btn_pick_all", Button)
                    break
                except Exception:
                    await asyncio.sleep(0.1)
            assert btn is not None, "Migrate All button never appeared"
            assert "Migrate All" in str(btn.label)

            btn.focus()
            await pilot.press("enter")
            await pilot.pause(0.2)

        assert picked == ["migrate_all"], f"Expected 'migrate_all' dismiss, got {picked}"
        log("test_channel_picker_migrate_all_button PASSED")
    except Exception as e:
        log(f"test_channel_picker_migrate_all_button FAILED: {e}")
        raise


def test_order_channels_for_display():
    """Display order: uncategorized first, then categories alphabetically,
    original order preserved within each group, duplicates dropped."""
    from types import SimpleNamespace
    from src.ui.modals import order_channels_for_display, group_channels_by_category

    def ch(cid, name, cat):
        return SimpleNamespace(id=cid, name=name, category_id=cat)

    channels = [
        ch(30, "beta-a", 2), ch(10, "lounge", None), ch(31, "beta-b", 2),
        ch(11, "spam", None), ch(30, "beta-a", 2), ch(20, "alpha-x", 1),
    ]
    cats = {1: "Alpha", 2: "Beta"}

    ordered = order_channels_for_display(channels, cats)
    assert [c.id for c in ordered] == [10, 11, 20, 30, 31]

    groups = group_channels_by_category(channels, cats)
    assert [g[0] for g in groups] == [None, 1, 2]
    assert [c.id for c in groups[0][1]] == [10, 11]

    # Dict-style channels (target pane) group by parent_id
    tgt = [{"id": "t9", "name": "n", "parent_id": 5}]
    assert [c["id"] for c in order_channels_for_display(tgt, {5: "Zeta"})] == ["t9"]


@pytest.mark.asyncio
async def test_channel_picker_display_order_matches_helper():
    """The source OptionList must render channels in order_channels_for_display order."""
    from types import SimpleNamespace
    from src.ui.modals import ChannelPickerScreen, order_channels_for_display
    from textual.widgets import OptionList

    def ch(cid, name, cat):
        return SimpleNamespace(id=cid, name=name, category_id=cat)

    src_channels = [
        ch(30, "beta-a", 2), ch(10, "lounge", None), ch(31, "beta-b", 2),
        ch(11, "spam", None), ch(20, "alpha-x", 1),
    ]
    cats = {1: "Alpha", 2: "Beta"}
    tgt_channels = [{"id": "t1", "name": "general", "type": 0, "parent_id": None}]

    class PickerApp(App):
        def compose(self):
            yield Label("base")

    app = PickerApp()
    async with app.run_test() as pilot:
        app.push_screen(ChannelPickerScreen(src_channels, cats, tgt_channels, {}))
        assert await wait_for_screen(app, ChannelPickerScreen)

        screen = app.screen
        src_list = None
        start = time.time()
        while time.time() - start < 5.0:
            try:
                src_list = screen.query_one("#src_list", OptionList)
                if src_list.option_count > 0:
                    break
            except Exception:
                pass
            await asyncio.sleep(0.1)
        assert src_list is not None and src_list.option_count > 0

        rendered_ids = []
        for i in range(src_list.option_count):
            opt = src_list.get_option_at_index(i)
            if opt.id and opt.id.startswith("src_"):
                rendered_ids.append(int(opt.id.split("_", 1)[1]))

        expected = [c.id for c in order_channels_for_display(src_channels, cats)]
        assert rendered_ids == expected, f"Picker order {rendered_ids} != display order {expected}"


def test_strip_migrated_mark():
    from src.ui.modals import MIGRATED_MARK, strip_migrated_mark
    assert strip_migrated_mark(f"{MIGRATED_MARK}general") == "general"
    assert strip_migrated_mark("general") == "general"
    assert "✓" in MIGRATED_MARK


@pytest.mark.asyncio
async def test_channel_picker_migrated_checkmark():
    """Migrated channels get a checkmark; name auto-matching still works."""
    from types import SimpleNamespace
    from src.ui.modals import ChannelPickerScreen, MIGRATED_MARK
    from textual.widgets import OptionList

    src_channels = [
        SimpleNamespace(id=1, name="general", category_id=None),
        SimpleNamespace(id=2, name="random", category_id=None),
    ]
    tgt_channels = [
        {"id": "t1", "name": "general", "type": 0, "parent_id": None},
        {"id": "t2", "name": "random", "type": 0, "parent_id": None},
    ]

    class PickerApp(App):
        def compose(self):
            yield Label("base")

    app = PickerApp()
    async with app.run_test() as pilot:
        app.push_screen(ChannelPickerScreen(src_channels, {}, tgt_channels, {}, "Fluxer", migrated_ids={1}))
        assert await wait_for_screen(app, ChannelPickerScreen)

        screen = app.screen
        src_list = None
        start = time.time()
        while time.time() - start < 5.0:
            try:
                src_list = screen.query_one("#src_list", OptionList)
                if src_list.option_count > 0:
                    break
            except Exception:
                pass
            await asyncio.sleep(0.1)

        prompts = {src_list.get_option_at_index(i).id: str(src_list.get_option_at_index(i).prompt)
                   for i in range(src_list.option_count)}
        assert prompts["src_1"].startswith(MIGRATED_MARK), "Migrated channel missing checkmark"
        assert "✓" not in prompts["src_2"], "Unmigrated channel should have no checkmark"

        # Auto-match must ignore the checkmark: highlight migrated 'general' -> target 't1'
        for i in range(src_list.option_count):
            if src_list.get_option_at_index(i).id == "src_1":
                src_list.highlighted = i
                break
        screen._auto_match_target()
        tgt_list = screen.query_one("#tgt_list", OptionList)
        assert tgt_list.highlighted is not None
        assert tgt_list.get_option_at_index(tgt_list.highlighted).id == "tgt_t1"
