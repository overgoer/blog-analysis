// Cloudflare Email Worker
// Routes: bizzy@inbound.pupupuuu.com → webhook with full email body
//
// Env vars to set in Cloudflare Dashboard:
//   WEBHOOK_URL = https://webhook.pupupuuu.com:8081/webhooks/catchall
//   WEBHOOK_SECRET = <same as CLOUDFLARE_API_SECRET on server>

export default {
  async email(message, env, ctx) {
    const WEBHOOK_URL = env.WEBHOOK_URL;
    const WEBHOOK_SECRET = env.WEBHOOK_SECRET;

    if (!WEBHOOK_URL) {
      console.error("WEBHOOK_URL not configured");
      return;
    }

    const from = message.from;
    const to = Array.isArray(message.to) ? message.to[0] : message.to;
    const subject = message.headers.get("subject") || "";
    const messageId = message.headers.get("message-id") || "";

    let textBody = "";
    let htmlBody = "";

    try {
      const tb = await message.textBody();
      if (tb) textBody = tb;
    } catch (e) { /* no text body */ }

    try {
      const hb = await message.htmlBody();
      if (hb) htmlBody = hb;
    } catch (e) { /* no html body */ }

    const payload = {
      source: "cloudflare-email-worker",
      from: from,
      to: to,
      subject: subject,
      message_id: messageId,
      text: textBody,
      html: htmlBody,
      timestamp: new Date().toISOString(),
    };

    try {
      const resp = await fetch(WEBHOOK_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Auth-Token": WEBHOOK_SECRET,
        },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        const text = await resp.text();
        console.error(`Webhook returned ${resp.status}: ${text}`);
      }
    } catch (err) {
      console.error(`Webhook fetch failed: ${err.message}`);
    }
  },
};
