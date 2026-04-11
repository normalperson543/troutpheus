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

class BaseModel(Model):
    """All models inherit this to share the database connection."""
    class Meta:
        database = db

class Trout(BaseModel):
    id = AutoField()
    target = TextField()
    actor = TextField()
    url = TextField()
    timestamp = DateTimeField(
        default=datetime.datetime.now,
        index=True)
class User(BaseModel):
    id = AutoField()
    user_id = TextField(unique=True)
    trouted_count = IntegerField(default=0)
    trouter_count = IntegerField(default=0)
    timestamp = DateTimeField(
        default=datetime.datetime.now,
        index=True)

print("Connecting to database")
db.connect()
print("Creating tables")
db.create_tables([Trout, User])
print("Done")

@app.command("/trout")
def respond_t(ack, command, client, body):
    # Acknowledge command request
    ack()
    #print(f"{command["text"]}")
    #respond(f"{command['text']}")

    split_command = command["text"].split(" ")
    pattern = r"^https:\/\/[\w-]+\.slack\.com\/archives\/([CGD][A-Z0-9]+)\/p(\d+)$"

    pat = re.compile(pattern)
    if (not split_command[0]):
        print("Help")
    if (split_command[1] and re.match(pat, split_command[1])):
        client.chat_postEphemeral(
            channel=body["channel_id"],
            user=body["user_id"],
            text=":trouted: *Whack!* That's not a valid message link! Try copying the message link again."
        )
        exit()
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
                        "text": f"{split_command[0]} has been *whacked* by a wet trout (<{split_command[1][1:-1]}|message>)\n\nDon't take this too seriously. Someone just wants to let you know that you did something silly."
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
                            "text": f"whacker: <@{body["user_id"]}> | <{os.getenv("TROUT_LOGS_CHANNEL")}|view all trouts>"
                        }
                    ]
                }
            ]
        )
    client.chat_postMessage(
        channel=os.getenv("TROUT_LOGS_CHANNEL"),
        text=f":trouted: {split_command[0]} *whacked* by a wet trout (<{split_command[1][1:-1]}|message>) (whacker: <@{body["user_id"]}>)"
    )
    target_id = split_command[0][2:14]
    Trout.create(target=target_id, actor=body["user_id"], url=split_command[1][1:-1])
    actor = User.get_or_create(user_id=body["user_id"])
    actor.trouter_count += 1
    actor.save()
    target = User.get_or_create(user_id=target_id)
    target.trouted_count += 1
    target.save()

@app.command("/trout-leaderboard")
def respond_tl(ack, client, body):
    ack()
    trouted_out = "#The Trouted\n"
    index = 0
    for user in User.select().order_by(User.trouted_count.desc()).limit(10):
        trouted_out += f"{index}. <@{user.user_id}> - `{user.trouted_count}`\n"
        index += 1
    whackers_out = "#The Whackers\n"
    index = 0
    for user in User.select().order_by(User.trouter_count.desc()).limit(10):
        whackers_out += f"{index}. <@{user.user_id}> - `{user.trouter_count}`\n"
        index += 1
    client.chat_postMessage(
        channel=body["channel_id"],
        blocks=[
            {
                "type": "markdown",
                "text": whackers_out
            }
	    ]
    )

@app.command("/trout-count")
def respond_tc(ack, client, body):
    ack()
    received_user = User.get_or_create(user_id=body["user_id"])
    client.chat_postMessage(
        channel = body["channel_id"],
        message = f"<@{received_user.user_id}> has been trouted `{received_user.trouted_count}` times and trouted others `{received_user.trouter_count}` times."
    )

@app.command("/trout-user-log")
def respond_tul(ack, command, client, body):
    ack()
    split_command = command["text"].split(" ")
    received_user = User.get_or_create(user_id=body["user_id"])
    trouted_out = f"#Trout user log\nFor <@{received_user.user_id}> (trouted by {received_user.trouted_count}), trouted ${received_user.trouter_count} others) - last 10 trouts\n"
    index = 0
    for trout in Trout.select().where().order_by(Trout.timestamp.desc()).limit(10):
        trouted_out += f":trouted: {trout} *whacked* by a wet trout (<{split_command[1][1:-1]}|message>) (whacker: <@{body["user_id"]}>)\n"
        index += 1


# Start your app
if __name__ == "__main__":
    SocketModeHandler(app, os.getenv("SLACK_API_TOKEN")).start()