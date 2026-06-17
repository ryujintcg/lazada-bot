DISCORD_BOT_TOKEN    = "your_discord_bot_token_here"
DISCORD_CHANNEL_ID   = "your_discord_channel_id_here"   # channel the bot posts to and reads replies from
DISCORD_USER_ID      = ""   # optional: your own Discord user ID. If set, only YOU can send OTP/commands.
LAZADA_PHONE         = "your_phone_number_here"          # e.g. 91234567
CAPTCHA_API_KEY      = ""   # optional: 2captcha API key to auto-solve CAPTCHAs (reCAPTCHA)
UPDATE_URL           = ""   # optional: override the update manifest URL (default is set in updater.py)

PRODUCTS = [
    {
        "name": "Product Name Here",
        "url":  "https://www.lazada.sg/products/your-product-url.html",
        "quantity": 1,  # Optional — remove this line to default to 1
    },
    # Add more products:
    # {
    #     "name": "Another Product",
    #     "url":  "https://www.lazada.sg/products/...",
    #     "quantity": 2,  # Optional — defaults to 1 if not set
    # },
]

CHECK_INTERVAL_SECONDS = 30
