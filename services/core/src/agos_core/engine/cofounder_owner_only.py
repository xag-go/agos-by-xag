"""The web's server actions the Co-Founder never does, each with its reason (pure
rules). engine/cofounder_parity/ re-exports `OWNER_ONLY` next to `DO` and `READS`;
tests/test_cofounder_parity.py fails on a web action none of the three lists.
"""

from __future__ import annotations

from agos_core.ops import catalog
from agos_core.ops.specs import SPECS
from agos_core.ops.specs.workspace import WHOLE_WORKSPACE

_HIS_VALUE = "a secret value (key, token, password) comes only from the owner, typed on his page"
_ACCESS = "who may use AGOS and which folders it sees: the owner's alone"
_OWN = "the Co-Founder's own power: never decided by itself"
_OTHER = "reads or copies another workspace or this machine: each workspace is closed off"
_UI = "the owner's own screen, chats and choices in the app"
_LIFE = WHOLE_WORKSPACE

OWNER_ONLY: dict[str, str] = {
    # the registry's owner-only operations (ops/specs: createWorkspace, deleteWorkspace)
    **catalog.owner_only(SPECS),
    # his own accounts elsewhere
    "linkTelegramAccount": "links the owner's own Telegram account to him",
    "startBotSetup": "a new bot is made with his own Telegram account and its token",
    "showHookSecret": "a webhook's signing secret is shown to the owner once, never to an agent",
    # access, folders
    "setWorkspaceAccess": _ACCESS,
    "saveAccessLists": _ACCESS,
    "setFolderAccess": _ACCESS,
    "addFolder": _ACCESS,
    "removeFolder": _ACCESS,
    "browseFolders": _ACCESS,
    "activateRemoteAccess": _ACCESS + " (opening AGOS to his other devices over Tailscale)",
    "turnOffRemoteAccess": _ACCESS + " (opening AGOS to his other devices over Tailscale)",
    "saveAlsoAllow": _ACCESS + " (which other Tailscale logins may open AGOS)",
    # AGOS itself
    "checkAgosUpdate": "updating AGOS itself (Settings → General → Update AGOS) is his call",
    "runAgosUpdate": "updating AGOS stops every workspace for minutes: only he starts it",
    # push
    "subscribePush": "his own phone's and browser's notifications",
    "unsubscribePush": "his own phone's and browser's notifications",
    "testPush": "his own phone's and browser's notifications",
    # secrets
    "startProviderLogin": "a model provider's login is his own account",
    "sendProviderLoginCode": "a model provider's login is his own account",
    "cancelProviderLogin": "a model provider's login is his own account",
    "logoutProvider": "a model provider's login is his own account",
    "saveApiKey": _HIS_VALUE,
    "testApiKey": "his model API keys (Settings → Models); the pool keys are do:list_pool_keys",
    "removeApiKey": "his model API keys (Settings → Models); the pool keys are do:remove_pool_key",
    "setBackupPassword": _HIS_VALUE,
    "addToolKey": _HIS_VALUE + "; the Co-Founder asks him for it with agos_ask_owner",
    "replaceToolKey": _HIS_VALUE + "; the Co-Founder asks him for it with agos_ask_owner",
    "saveGithubToken": _HIS_VALUE,
    "setConnectorSecret": _HIS_VALUE,
    "setWorkspaceComposioKey": _HIS_VALUE,
    "setToolService": _HIS_VALUE + " (a tool service's keys, for every workspace)",
    "addConnection": _HIS_VALUE + " (a bot's token)",
    "makeMcpToken": _HIS_VALUE + " (AGOS's own MCP token, shown once)",
    "removeMcpToken": "AGOS's own MCP tokens belong to the apps he connected himself",
    "composioLink": "Composio's login is his own account (its key is a secret)",
    "composioSetUp": "Composio's login is his own account (its key is a secret)",
    "removeComposioAccount": "Composio's login is his own account (its key is a secret)",
    "deleteConnection": "the bot and its token are his (a new one needs his Telegram)",
    # the Co-Founder's own power
    "setAutonomy": _OWN,
    "saveCofounderActionsMode": _OWN,
    "decideCofounderAction": _OWN,
    "decideCapability": _OWN,
    "answerApproval": _OWN,
    "decideProposal": _OWN,
    "undoProposal": _OWN,
    "decideHeld": _OWN,
    "answerKanbanAsk": _OWN + " (his answer to an agent's question)",
    "answerQuestion": _OWN + " (his answer to an agent's question)",
    "answerCard": _OWN + " (his answer to a card waiting for him)",
    "answerCardTokens": _OWN + " (his yes to a card's spend)",
    "saveIdentity": _OWN + " (its own SOUL.md: agos_propose kind instructions)",
    "setChatAccess": _OWN + " (Full access in a chat)",
    "voteOn": "his own opinion of the agents' work",
    "saveOwnerName": "his own name, the person the Founder box stands for",
    "saveFounderTitle": "the title on his own Founder box",
    # another workspace or this machine
    "copyAgentHere": _OTHER,
    "copySkillHere": _OTHER,
    "listCopyableSkills": _OTHER,
    "listOnThisMachine": _OTHER,
    "importFromMachine": _OTHER,
    # whole workspaces
    "archiveWorkspace": _LIFE,
    "unarchiveWorkspace": _LIFE,
    "restoreWorkspace": _LIFE,
    "purgeWorkspace": _LIFE,
    "uploadWorkspaceIcon": "a picture from his own device",
    "removeWorkspaceIcon": "the workspace's picture he chose",
    # his own chats and screen
    "createChat": _UI,
    "sendChatMessage": _UI,
    "editChatMessage": _UI,
    "deleteChatMessage": _UI,
    "stopChat": _UI,
    "retryChat": _UI,
    "renameChat": _UI,
    "setChatModel": _UI,
    "deleteChat": _UI,
    "setChatAgent": _UI,
    "openDm": _UI,
    "openCardChatId": _UI,
    "markItem": _UI + " (his Inbox marks)",
    "unmarkItem": _UI + " (his Inbox marks)",
    "saveUsagePrefs": _UI,
    "saveTabsOrder": _UI,
    "saveWorkspaceOrder": _UI,
    "annotateCardDoc": _UI + " (his comments on a document; agents answer with agos_card_document)",
    "deleteAnnotation": _UI + " (his own comment; the Co-Founder resolves it instead)",
    "removeCardFile": _UI + " (a file he attached; agents add files with kanban_attach)",
}
