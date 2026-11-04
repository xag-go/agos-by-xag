"""Click tests: the owner's main flows, clicked like he clicks them, on the real web
build against the light rig (rig.py). Each test works in the "Flows" workspace and
checks what the page shows after the click, then after a reload (it was saved).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from playwright.sync_api import expect

from browser import pages


def _open(page: Any, rig: Any, path: str) -> None:
    page.goto(f"/w/{rig.flows}{path}")
    pages.ready(page)


def test_owner_creates_a_card(page: Any, rig: Any) -> None:
    _open(page, rig, "/kanban")
    page.get_by_role("link", name="New card").or_(
        page.get_by_role("button", name="New card")
    ).first.click()
    dialog = page.locator("dialog[open]", has_text="Create card")
    dialog.get_by_label("Title").fill("Ship the browser tests")
    dialog.get_by_role("button", name="Create card").click()
    expect(page.locator("dialog[open]", has_text="Create card")).to_have_count(0)
    card = page.locator("main").get_by_text("Ship the browser tests", exact=True)
    expect(card.first).to_be_visible()
    page.reload()
    pages.ready(page)
    expect(
        page.locator("main").get_by_text("Ship the browser tests", exact=True).first
    ).to_be_visible()


def test_owner_moves_a_card_to_blocked_and_back(page: Any, rig: Any) -> None:
    _open(page, rig, "/kanban")
    page.get_by_role("button", name="Select", exact=True).click()
    page.get_by_role("button", name=re.compile("Fix the login bug")).click()
    page.get_by_label("Move", exact=True).select_option("block")
    blocked = page.locator("main a, main button").filter(has_text="Fix the login bug")
    expect(blocked.first).to_have_class(re.compile("border-danger"))
    page.reload()
    pages.ready(page)
    card = page.locator("main a").filter(has_text="Fix the login bug").first
    expect(card).to_have_class(re.compile("border-danger"))
    # And back: Unblock.
    page.get_by_role("button", name="Select", exact=True).click()
    page.get_by_role("button", name=re.compile("Fix the login bug")).click()
    page.get_by_label("Move", exact=True).select_option("unblock")
    page.reload()
    pages.ready(page)
    expect(page.locator("main a").filter(has_text="Fix the login bug").first).not_to_have_class(
        re.compile("border-danger")
    )


def test_owner_opens_a_card_and_each_of_its_tabs(page: Any, rig: Any) -> None:
    _open(page, rig, "/kanban")
    page.locator("main a").filter(has_text="Write the launch post").first.click()
    dialog = page.locator("dialog[open]", has_text="Write the launch post")
    expect(dialog).to_be_visible()
    expect(page).to_have_url(re.compile(r"card=t_"))
    tabs = dialog.get_by_role("tab")
    names = [t.strip() for t in tabs.all_inner_texts()]
    assert {"Description", "Documents", "Review", "Steps", "Comments", "Chat"} <= set(names), names
    for name in names:
        tab = dialog.get_by_role("tab", name=name, exact=True)
        tab.click()
        expect(tab).to_have_attribute("aria-selected", "true")
        expect(dialog.get_by_role("tabpanel").first).to_be_visible()
    dialog.get_by_role("tab", name="Description", exact=True).click()
    expect(dialog.get_by_text("Details for Write the launch post")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("dialog[open]")).to_have_count(0)


def test_owner_sends_a_chat_message_and_the_answer_comes(page: Any, rig: Any) -> None:
    chat = rig.state["flows_seed"]["chat"]
    _open(page, rig, f"/sessions?chat={chat}")
    box = page.get_by_label("Message")
    box.fill("What should we ship first?")
    page.get_by_role("button", name="Send", exact=True).click()
    thread = page.get_by_role("region", name="Planning chat")
    expect(thread.get_by_text("What should we ship first?").first).to_be_visible()
    answer = re.compile(r"Fake answer: .*What should we ship first\?")
    expect(thread.get_by_text(answer)).to_be_visible(timeout=30_000)
    page.reload()
    pages.ready(page)
    expect(page.get_by_role("region", name="Planning chat").get_by_text(answer)).to_be_visible()


def test_owner_approves_a_hire_in_the_inbox_and_undoes_it(page: Any, rig: Any) -> None:
    _open(page, rig, "/inbox")
    item = (
        page.locator("main article, main li, main section, main div")
        .filter(has_text="Script Writer")
        .filter(has=page.get_by_role("button", name="Approve"))
        .last
    )
    item.get_by_role("button", name="Approve").click()
    toast = page.get_by_role("button", name="Undo")
    expect(toast).to_be_visible()
    expect(page.locator("main").get_by_role("button", name="Approve")).to_have_count(
        1
    )  # the plan's
    hired = page.request.get(
        f"{rig.core}/workspaces/{rig.flows}/agents", headers=_core_headers(rig)
    )
    assert "script-writer" in hired.text()
    toast.click()
    expect(page.get_by_text(re.compile("Undone"))).to_be_visible()
    gone = page.request.get(f"{rig.core}/workspaces/{rig.flows}/agents", headers=_core_headers(rig))
    assert "script-writer" not in gone.text()


def test_owner_saves_workspace_settings_and_puts_them_back(page: Any, rig: Any) -> None:
    _open(page, rig, "/settings")
    form = page.locator("form").filter(has=page.get_by_role("button", name="Save changes"))
    about = form.locator("textarea").first
    before = about.input_value()
    about.fill("Browser test: the owner's words")
    form.get_by_role("button", name="Save changes").click()
    expect(form.get_by_role("button", name="Save changes")).to_be_enabled()
    page.reload()
    pages.ready(page)
    form = page.locator("form").filter(has=page.get_by_role("button", name="Save changes"))
    expect(form.locator("textarea").first).to_have_value("Browser test: the owner's words")
    form.locator("textarea").first.fill(before)
    form.get_by_role("button", name="Save changes").click()
    expect(form.get_by_role("button", name="Save changes")).to_be_enabled()
    page.reload()
    pages.ready(page)
    form = page.locator("form").filter(has=page.get_by_role("button", name="Save changes"))
    expect(form.locator("textarea").first).to_have_value(before)


def test_owner_turns_an_automation_off_and_on(page: Any, rig: Any) -> None:
    _open(page, rig, "/automations")
    switch = page.get_by_role("switch", name="Daily brief on or off")
    expect(switch).to_have_attribute("aria-checked", "true")
    switch.click()
    expect(switch).to_have_attribute("aria-checked", "false")
    page.wait_for_load_state("networkidle")
    page.reload()
    pages.ready(page)
    switch = page.get_by_role("switch", name="Daily brief on or off")
    expect(switch).to_have_attribute("aria-checked", "false")
    switch.click()
    page.wait_for_load_state("networkidle")
    page.reload()
    pages.ready(page)
    expect(page.get_by_role("switch", name="Daily brief on or off")).to_have_attribute(
        "aria-checked", "true"
    )


def _core_headers(rig: Any) -> dict[str, str]:
    return {"x-agos-internal": Path(rig.state["token_file"]).read_text().strip()}
