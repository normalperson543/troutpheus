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
class User(BaseModel):
    id = AutoField()
    username = TextField(default="")
    user_id = TextField(unique=True)
    trouted_count = IntegerField(default=0)
    trouter_count = IntegerField(default=0)
    timestamp = DateTimeField(
        default=datetime.datetime.now,
        index=True)
class Trout(BaseModel):
    id = AutoField()
    target = TextField()
    actor = TextField()
    thread_id = TextField(default="")
    channel_id = TextField(default="")
    reason = TextField(default="")
    timestamp = DateTimeField(
        default=datetime.datetime.now,
        index=True)


print("Connecting to database")
db.connect()
print("Creating tables")
db.create_tables([Trout, User])
print("Done")

TROUT_HELP = f"*:trouted: Troutpheus commands*\n\n`/trout @USER [REASON]` - Tells the user they made a mistake\n`/trout-leaderboard` - Posts the top 10 trouted users and whackers\n`trout-count @USER` - Posts how many times you got trouted and whacked others\n\nTrout logs: <#{os.getenv("TROUT_LOGS_CHANNEL")}>\nFor support, DM @normalperson543 or drop a message in that channel :p"

username_pattern = r"^<@[UW][A-Z0-9]{8,11}(?:\|[a-z0-9._-]+)?>"
username_pat = re.compile(username_pattern)

@app.command("/trout")
def respond_t(ack, command, client, body, respond):
    # Acknowledge command request
    ack()

    split_command = command["text"].split(" ")
    pattern = r"^<https:\/\/[\w-]+\.slack\.com\/archives\/([CGD][A-Z0-9]+)\/p(\d+)>$"
    reason = ""
    pat = re.compile(pattern)
    print(split_command)
    if split_command[0] == "":
        respond(
            text=TROUT_HELP
        )
        exit()
    elif len(split_command) == 1:
        respond(
            text=":trouted: *Whack!* You should enter a reason to why you're whacking this user. The syntax for trouting someone is `/trout @USER [REASON]`."
        )
        exit()
    elif not re.match(pat, split_command[1]):
        reason = " ".join(split_command[1:])
        if len(reason) > 100:
            respond(f":trouted: *Whack!* Your reason can't be over 100 characters (it is {len(reason)} characters long). Please edit it so your reason is <= 100 characters.\n\nYou said: ```{reason}```")
            exit()
    else:
        reason = split_command[1][1:-1]
    print(split_command)
    if not re.match(username_pat, split_command[0]):
        respond(":trouted: *Whack!* That's not a valid user. The syntax for trouting someone is `/trout @USER [REASON]`.")
        exit()
    target_id = split_command[0][2:]
    target_id = target_id[:target_id.index("|")]
    print(body["user_id"])
    Trout.create(target=target_id, actor=body["user_id"], reason=reason)
    actor, created = User.get_or_create(user_id=body["user_id"])
    actor.trouter_count += 1
    if len(actor.username) == 0:
        slack_user = client.users_info(user=body["user_id"])
        actor.username = slack_user["user"]["name"]
    actor.save()
    target, created = User.get_or_create(user_id=target_id)
    if len(target.username) == 0:
        slack_user = client.users_info(user=target_id)
        actor.username = slack_user["user"]["name"]
    target.trouted_count += 1
    target.save()
    respond(
        response_type="in_channel",
        text=f"{target.username} has been *whacked* by a wet trout :3\n\nDon't take this too seriously. Someone just wants to let you know that you did something silly.\nReason: {reason}",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Whack!* <@{target.user_id}> (:trouted:{target.trouted_count}) has been *whacked* by a wet trout :3\n\n\nDon't take this too seriously. Someone just wants to let you know that you did something silly.\n>{reason}"
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
                        "text": f"whacker: <@{actor.user_id}> (:trouted:{target.trouted_count}) | <#{os.getenv("TROUT_LOGS_CHANNEL")}>"
                    }
                ]
            }
        ]
    )
    client.chat_postMessage(
        channel=os.getenv("TROUT_LOGS_CHANNEL"),
        text=f":trouted: *{target.username}* ({target.user_id}) (:trouted:{target.trouted_count}) *whacked* by *{actor.username}* ({actor.user_id}) (:trouted:{actor.trouted_count}) with a wet trout\n\n>{reason if len(reason) > 0 else f"<{reason}|message>"}"
    )

@app.command("/trout-leaderboard")
def respond_tl(ack, respond):
    ack()
    out = "*:trouted: Top Trouted*\n"
    index = 1
    for user in User.select().order_by(User.trouted_count.desc()).limit(10):
        out += f"{index}. *{user.username}* ({user.user_id}) - `{user.trouted_count}`\n"
        index += 1
    out += "\n*:trouted: Top Whackers*\n"
    index = 1
    for user in User.select().order_by(User.trouter_count.desc()).limit(10):
        out += f"{index}. *{user.username}* ({user.user_id}) - `{user.trouter_count}`\n"
        index += 1
    respond(
        response_type="in_channel",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": out
                }
            }
	    ]
    )

@app.command("/trout-count")
def respond_tc(ack, respond, command):
    ack()
    split_command = command["text"].split(" ")
    if split_command[0] == "":
        respond(
            text=TROUT_HELP
        )
        exit()
    
    if not re.match(username_pat, split_command[0]):
        respond(":trouted: *Whack!* That's not a valid user. The syntax for getting someone's trout count is `/trout-count @USER`.")
        exit()
    target_id = split_command[0][2:]
    target_id = target_id[:target_id.index("|")]
    received_user = User.get(user_id=target_id)
    respond(
        response_type="in_channel",
        text = f":trouted: *{received_user.username}* ({received_user.user_id}) has been trouted `{received_user.trouted_count}` times and trouted others `{received_user.trouter_count}` times."
    )


# Start your app
if __name__ == "__main__":
    SocketModeHandler(app, os.getenv("SLACK_API_TOKEN")).start()