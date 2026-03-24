# Vercel Deployment — Not Applicable

The Telegram Bot uses **long-polling** to receive messages from the Telegram API.  Long-polling requires a persistent, always-running process — which is incompatible with Vercel's serverless (function-per-request) model.

**Vercel is not supported for this bot.**

## Alternatives

| Platform | Cost | Notes |
|---|---|---|
| **Railway** | ~$0–5/mo | ⭐ Recommended — see [RAILWAY.md](RAILWAY.md) |
| **Fly.io** | Free tier available | Docker-based; global regions |
| **Render** (paid) | ~$7/mo | Free tier sleeps after inactivity |
| **Oracle Cloud** | Free forever | 2 free ARM VMs; full Linux control |
| **Linux VPS** | ~$5/mo | Full control; see [PLATFORM.md](PLATFORM.md) |
| **Docker (self-hosted)** | Varies | Run anywhere; see [PLATFORM.md](PLATFORM.md) |

## Webhook Alternative (Advanced)

If you specifically need a serverless/webhook setup, you can configure the Telegram bot to use **webhooks** instead of polling.  This requires:

1. A public HTTPS URL (e.g. a Vercel function or Cloudflare Worker endpoint).
2. Registering the webhook URL with Telegram:
   ```
   https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://your-domain.com/webhook
   ```
3. Modifying `bot.py` to use `Application.run_webhook()` instead of `run_polling()`.

This is significantly more complex.  For most users, Railway polling is the right choice.
