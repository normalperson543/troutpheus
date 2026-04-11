import os
import re
import datetime
from peewee import *
from playhouse.postgres_ext import *
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv

load_dotenv()

# Initializes your app with your bot token and socket mode handler
app = App(token=os.getenv("SLACK_BOT_TOKEN"))
COMMIT_ID = os.getenv("SOURCE_COMMIT")

db = PostgresqlExtDatabase(os.getenv("DATABASE_URL"))


@app.command("/trout")
def respond_t(ack, respond, command, client, body):
    # Acknowledge command request
    ack()
    #print(f"{command["text"]}")
    #respond(f"{command['text']}")

    split_command = command["text"].split(" ")
    pattern = r"^https:\/\/[\w-]+\.slack\.com\/archives\/([CGD][A-Z0-9]+)\/p(\d+)$"

    pat = re.compile(pattern)
    if (split_command[1] and re.match(pat, split_command[1])):
        client.chat_postEphemeral(
            channel=body["channel_id"],
            user=body["user_id"],
            text=":trouted: *Whack!* That's not a valid message link! Try copying the message link again."
        )
        exit()
    print(f"{split_command[0]} has been *whacked* by a wet trout for <{split_command[1][1:-1]}|this message>.\n\nDon't take this too seriously. Someone just wants to let you know that you did something silly.")
    client.chat_postMessage(
            channel=body["channel_id"],
            blocks=[
                {
                    "type": "markdown",
                    "text": "## Whack!"
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{split_command[0]} has been *whacked* by a wet trout for <{split_command[1][1:-1]}|this message>.\n\nDon't take this too seriously. Someone just wants to let you know that you did something silly."
                    },
                    "accessory": {
                        "type": "image",
                        "image_url": "https://user-cdn.hackclub-assets.com/019d711a-37ab-7422-a375-b7bcd3629304/Rainbow_trout_transparent.png",
                        "alt_text": "rainbow trout"
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"whacker: <@{body["user_id"]}> | view leaderboard | view all trouts"
                        }
                    ]
                }
            ]
        )

# Start your app
if __name__ == "__main__":
    SocketModeHandler(app, os.getenv("SLACK_API_TOKEN")).start()