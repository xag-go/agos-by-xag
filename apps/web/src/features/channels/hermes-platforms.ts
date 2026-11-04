/**
 * Messaging platforms Hermes supports (its gateway docs). AGOS connects a
 * workspace to the ones it has a driver for; the rest are listed as coming.
 */
export const HERMES_PLATFORMS: { key: string; title: string; about: string }[] =
  [
    { key: "slack", title: "Slack", about: "A Slack bot (Socket Mode)." },
    { key: "discord", title: "Discord", about: "A Discord bot." },
    {
      key: "whatsapp",
      title: "WhatsApp",
      about: "WhatsApp or WhatsApp Business.",
    },
    { key: "signal", title: "Signal", about: "Signal messenger." },
    { key: "email", title: "Email", about: "An inbox (IMAP/SMTP)." },
    { key: "teams", title: "Microsoft Teams", about: "A Teams bot." },
    { key: "google_chat", title: "Google Chat", about: "A Google Chat bot." },
    { key: "matrix", title: "Matrix", about: "A Matrix bot." },
    { key: "mattermost", title: "Mattermost", about: "A Mattermost bot." },
    { key: "sms", title: "SMS", about: "Text messages (Twilio)." },
    {
      key: "imessage",
      title: "iMessage",
      about: "Through BlueBubbles or Photon.",
    },
    { key: "line", title: "LINE", about: "A LINE bot." },
    { key: "wechat", title: "WeChat / WeCom", about: "WeChat and WeCom." },
    { key: "feishu", title: "Feishu / Lark", about: "A Feishu or Lark bot." },
    { key: "dingtalk", title: "DingTalk", about: "A DingTalk bot." },
    { key: "irc", title: "IRC", about: "An IRC bot." },
    { key: "simplex", title: "SimpleX", about: "SimpleX Chat." },
    { key: "ntfy", title: "ntfy", about: "Push notifications." },
    {
      key: "webhooks",
      title: "Webhooks",
      about: "Events from GitHub, GitLab…",
    },
  ];
