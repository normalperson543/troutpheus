import os
import re
import datetime
from peewee import *
from playhouse.postgres_ext import *
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv
import sentry_sdk
from slack_sdk.errors import SlackApiError


load_dotenv()

print("init sentry...")
sentry_sdk.init(
    dsn=os.getenv("SENTRY_URL"),
    # Add data like request headers and IP for users,
    # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
    send_default_pii=False,
    enable_logs=True,
    environment=os.getenv("ENVIRONMENT")
)
# Initializes your app with your bot token and socket mode handler
sentry_sdk.logger.info("starting bot")
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
    unsubscribed = BooleanField(default=False)
class Trout(BaseModel):
    id = AutoField()
    target = TextField()
    actor = TextField()
    reason = TextField(default="")
    timestamp = DateTimeField(
        default=datetime.datetime.now,
        index=True)

print("Connecting to database")
db.connect()
print("Creating tables")
db.create_tables([Trout, User])
print("Done")

TROUT_HELP = f"*:trouted: Troutpheus commands*\n\n`/trout @USER [REASON]` - Tells the user they made a mistake\n`/trout-leaderboard` - Posts the top 10 trouted users and whackers\n`/trout-count @USER` - Posts how many times you got trouted and whacked others\n`/trout-user-logs @USER` - Posts the last 10 trouts of a user\n\nTrout logs: <#{os.getenv("TROUT_LOGS_CHANNEL")}>\nFor support, DM @normalperson543 or drop a message in that channel :p"

username_pattern = r"^<@[UW][A-Z0-9]{8,11}(?:\|[a-z0-9._-]+)?>"
username_pat = re.compile(username_pattern)

def trout(actor_id, target_id, channel_id, reason, client, respond):
    sentry_sdk.logger.info(f"target {target_id} trouted by actor {actor_id} in {channel_id}")
    sentry_sdk.metrics.count(
        "trout",
        1,
        attributes={
            "target": target_id,
            "actor": actor_id,
            "channel_id": channel_id
        },
    )

    actor, created_actor = User.get_or_create(user_id=actor_id)
    if len(actor.username) == 0:
        slack_user = client.users_info(user=actor_id)
        actor.username = slack_user["user"]["name"]
        sentry_sdk.logger.info(f"actor new username: {actor.user_id} --> {actor.username}")
    

    target, created_target = User.get_or_create(user_id=target_id)
    if len(target.username) == 0:
        slack_user = client.users_info(user=target_id)
        target.username = slack_user["user"]["name"]
        sentry_sdk.logger.info(f"target new username: {target.user_id} --> {target.username}")
    
    actor.trouter_count += 1
    actor.save()

    target.trouted_count += 1
    target.save()

    Trout.create(target=target_id, actor=actor_id, reason=reason)

    if not target.unsubscribed:
        dm_resp = app.client.conversations_open(users=target_id)
        dm_channel_id = dm_resp["channel"]["id"]
        try:
            client.chat_postMessage(
                channel=dm_channel_id,
                text=f"Whack! You've just been whacked with a wet trout by <@{actor.user_id}> :3 Don't take this too seriously. Someone just wants to let you know that you did something silly. Reason: {reason}",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Whack!* You've just been *whacked* with a wet trout by <@{actor.user_id}> :3\n\nDon't take this too seriously. Someone just wants to let you know that you did something silly. <{os.getenv("SUPPORT_CANVAS")}|What's a trout?>\n>{reason}"
                        },
                        "accessory": {
                            "type": "image",
                            "image_url": "https://user-cdn.hackclub-assets.com/019d711a-37ab-7422-a375-b7bcd3629304/Rainbow_trout_transparent.png",
                            "alt_text": "rainbow trout"
                        }
                    },
                    {
                        
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "Whack them back",
                                },
                                "style": "primary",
                                "value": target_id,
                                "action_id": "troutback_button"
                            },
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "Unsubscribe from trout DMs",
                                },
                                "style": "danger",
                                "value": "unsub_button",
                                "action_id": "unsub_button"
                            }
                        ]
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"you've been trouted {target.trouted_count} times and trouted {target.trouter_count} others | `/trout @[USER] [REASON]` | <#{os.getenv("TROUT_LOGS_CHANNEL")}>"
                            }
                        ]
                    }
                ],
                unfurl_links=False
            )
        except SlackApiError:
            sentry_sdk.logger.warning("cannot send message to bot")
            
    
    respond(
        response_type="in_channel",
        text=f"{target.username} has been *whacked* by a wet trout :3\n\nDon't take this too seriously. Someone just wants to let you know that you did something silly.\nReason: {reason}",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Whack!* *@{target.username}* (:trouted:{target.trouted_count}) has been *whacked* by a wet trout :3\n\n\nDon't take this too seriously. Someone just wants to let you know that you did something silly.\n>{reason}"
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
                        "text": f"whacker: *@{actor.username}* (:trouted:{actor.trouted_count}) | `/trout @[USER] [REASON]` | <#{os.getenv("TROUT_LOGS_CHANNEL")}>"
                    }
                ]
            }
        ]
    )

    
    client.chat_postMessage(
        channel=os.getenv("TROUT_LOGS_CHANNEL"),
        text=f":siren1: *{target.username}* ({target.user_id}) (:trouted:{target.trouted_count}) was *whacked* by *{actor.username}* ({actor.user_id}) (:trouted:{actor.trouted_count}) with a wet trout\n\n>{reason}",
        unfurl_links=False
    )
@app.command("/trout")
def respond_t(ack, command, body, respond, client):
    # Acknowledge command request
    ack()
    sentry_sdk.logger.info(f"responding to trouting req from {body["user_id"]} in {body["channel_id"]}")

    split_command = command["text"].split(" ")
    pattern = r"^<https:\/\/[\w-]+\.slack\.com\/archives\/([CGD][A-Z0-9]+)\/p(\d+)>$"
    reason = ""
    pat = re.compile(pattern)
    if split_command[0] == "":
        sentry_sdk.logger.info(f"no user passed in, responding with help")
        respond(
            text=TROUT_HELP
        )
        exit()
    elif len(split_command) == 1:
        sentry_sdk.logger.info(f"no reason passed in, responding with reason error")
        respond(
            text=":trouted: *Whack!* You should enter a reason to why you're whacking this user. The syntax for trouting someone is `/trout @USER [REASON]`."
        )
        exit()
    elif not re.match(pat, split_command[1]):
        reason = " ".join(split_command[1:])
        if len(reason) > 200:
            sentry_sdk.logger.info(f"reason too long")
            respond(f":trouted: *Whack!* Your reason can't be over 200 characters (it is {len(reason)} characters long). Please edit it so your reason is <= 200 characters.\n\nYou said: ```{reason}```")
            exit()
    else:
        reason = split_command[1][1:-1]
    if not re.match(username_pat, split_command[0]):
        sentry_sdk.logger.info(f"attempted to trout {split_command[0]} but it is not a valid user")
        respond(":trouted: *Whack!* That's not a valid user. The syntax for trouting someone is `/trout @USER [REASON]`.")
        exit()
    target_id = split_command[0][2:]
    target_id = target_id[:target_id.index("|")]
    actor_id = body["user_id"]

    trout(actor_id, target_id, body["channel_id"], reason, client, respond)
    

@app.command("/trout-leaderboard")
def respond_tl(ack, body, respond):
    ack()
    sentry_sdk.metrics.count(
        "trout_leaderboard",
        1,
        attributes={
            "channel_id": body["channel_id"],
            "actor": body["user_id"]
        },
    )
    sentry_sdk.logger.info(f"responding to leaderboard req from {body["user_id"]} in {body["channel_id"]}")
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
def respond_tc(ack, respond, body, command):
    ack()
    sentry_sdk.logger.info(f"responding to trout count req from {body["user_id"]} in {body["channel_id"]}")
    split_command = command["text"].split(" ")
    if split_command[0] == "":
        sentry_sdk.logger.info("no user passed in for trout count req, responding with help")
        respond(
            text=TROUT_HELP
        )
        exit()
    
    if not re.match(username_pat, split_command[0]):
        sentry_sdk.logger.info(f"attempted to get stats for {split_command[0]} but it is not a valid user")
        respond(":trouted: *Whack!* That's not a valid user. The syntax for getting someone's trout count is `/trout-count @USER`.")
        exit()
    target_id = split_command[0][2:]
    target_id = target_id[:target_id.index("|")]
    sentry_sdk.logger.info(f"identified the stat req for {target_id}")
    sentry_sdk.metrics.count(
        "trout_count",
        1,
        attributes={
            "channel_id": body["channel_id"],
            "actor": body["user_id"],
            "target": target_id
        },
    )
    try:
        received_user = User.get(user_id=target_id)
    except User.DoesNotExist:
        sentry_sdk.logger.info(f"cannot find user {target_id}")
        respond(
            text = "*Whack!* The user you entered hasn't used Troutpheus yet. Check the username you entered, and try again. For reference, the correct syntax is `/trout-count @[USER]`."
        )
        exit()
    respond(
        response_type="in_channel",
        text = f":trouted: *{received_user.username}* ({received_user.user_id}) has been trouted `{received_user.trouted_count}` times and trouted others `{received_user.trouter_count}` times."
    )

@app.action("unsub_button")
def unsub(ack, body, say):
    ack()
    sentry_sdk.logger.info(f"responding to unsub req from {body["user"]["id"]}")
    sentry_sdk.metrics.count(
        "unsub",
        1,
        attributes={
            "actor": body["user"]["id"],
        },
    )
    target_id=body["user"]["id"]
    user = User.get(user_id=target_id)
    user.unsubscribed = True
    user.save() 
    say(
        response_type="in_channel",
        text="You've successfully unsubscribed from getting DMs about you being trouted.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":red-x: You've successfully unsubscribed from getting DMs about you being trouted."
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Resubscribe to trout DMs",
                        },
                        "style": "primary",
                        "value": "resub_button",
                        "action_id": "resub_button"
                    }
                ]
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"<#{os.getenv("TROUT_LOGS_CHANNEL")}>"
                    }
                ]
            }
        ]
    )
@app.action("resub_button")
def resub(ack, body, say):
    ack()
    sentry_sdk.logger.info(f"responding to resub req from {body["user"]["id"]}")
    sentry_sdk.metrics.count(
        "resub",
        1,
        attributes={
            "actor": body["user"]["id"],
        },
    )
    target_id=body["user"]["id"]
    user = User.get(user_id=target_id)
    user.unsubscribed = False
    user.save()
    say(
        response_type="in_channel",
        text="You've successfully resubscribed to getting DMs about you being trouted.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":white_check_mark: You've successfully resubscribed to getting DMs about you being trouted."
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Unsubscribe from trout DMs",
                        },
                        "style": "danger",
                        "value": "unsub_button",
                        "action_id": "unsub_button"
                    }
                ]
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"<#{os.getenv("TROUT_LOGS_CHANNEL")}>"
                    }
                ]
            }
        ]
    )

@app.action("troutback_button")
def troutback_modal_open(ack, body, client):
    ack()
    sentry_sdk.logger.info(f"responding to troutback button press from {body["user"]["id"]} to {action["value"]}")
    action = body["actions"][0]
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "title": {
                "type": "plain_text",
                "text": "Trout someone back >:3",
                "emoji": True
            },
            "callback_id": "troutback",
            "submit": {
                "type": "plain_text",
                "text": "Trout them :devious-ahh:",
                "emoji": True
            },
            "type": "modal",
            "close": {
                "type": "plain_text",
                "text": "nah i change my mind",
                "emoji": True
            },
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*You're about to whack <@{action["value"]}> back with a trout!* Enter the reason why you're trouting them back."
                    }
                },
                {
                    "type": "input",
                    "element": {
                        "type": "plain_text_input",
                        "multiline": True,
                        "action_id": "plain_text_input-action"
                    },
                    "label": {
                        "type": "plain_text",
                        "text": "Trout reason",
                        "emoji": True
                    },
                    "optional": False
                }
            ]
        }
    )

@app.view("troutback")
def handle_troutback_submit(ack, body, view, client):
    ack()
    name = view["state"]["values"]["name_block"]["name_input"]["value"]

@app.command("/trout-user-log")
def respond_tul(ack, command, respond, body):
    ack()
    sentry_sdk.logger.info(f"responding to trout user log req from {body["user_id"]} in {body["channel_id"]}")
    split_command = command["text"].split(" ")
    if split_command[0] == "":
        sentry_sdk.logger.info("no user passed in for trout user log req, responding with help")
        respond(
            text=TROUT_HELP
        )
        exit()
    
    if not re.match(username_pat, split_command[0]):
        sentry_sdk.logger.info(f"attempted to get user log for {split_command[0]} but it is not a valid user")
        respond(":trouted: *Whack!* That's not a valid user. The syntax for getting someone's trout count is `/trout-count @USER`.")
        exit()
    target_id = split_command[0][2:]
    target_id = target_id[:target_id.index("|")]
    sentry_sdk.logger.info(f"identified the user log req for {target_id}")
    sentry_sdk.metrics.count(
        "trout_user_log",
        1,
        attributes={
            "channel_id": body["channel_id"],
            "actor": body["user_id"],
            "target": target_id
        },
    )
    try:
        received_user = User.get(user_id=target_id)
    except User.DoesNotExist:
        sentry_sdk.logger.info(f"cannot find user {target_id}")
        respond(
            text = "*Whack!* The user you entered hasn't used Troutpheus yet. Check the username you entered, and try again. For reference, the correct syntax is `/trout-user-log @[USER]`."
        )
        exit()
    trouted_out = f"*:trouted: Trout user log*\nFor <@{received_user.user_id}> ({received_user.user_id}) (trouted by `{received_user.trouted_count}`, trouted `{received_user.trouter_count}` others) - last 10 trouts\n\n*Trouted by others*\n\n"
    for trout in Trout.select().where(Trout.target == split_command[0][2:13]).order_by(Trout.timestamp.desc()).limit(10):
        timestamp = trout.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        trouted_out += f"- *{timestamp}*: <@{trout.target}> *whacked* by a wet trout by <@{trout.actor}>: {trout.reason}\n"
    trouted_out += "\n\n*Trouted others*\n\n"
    for trout in Trout.select().where(Trout.actor == split_command[0][2:13]).order_by(Trout.timestamp.desc()).limit(10):
        timestamp = trout.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        trouted_out += f"- *{timestamp}*: <@{trout.target}> *whacked* by a wet trout by <@{trout.actor}>: {trout.reason}\n"
    sentry_sdk.logger.info(f"finished getting the user log stats for {target_id}")
    respond(
        text = trouted_out,
        unfurl_links=False
    )

# Start your app
if __name__ == "__main__":
    SocketModeHandler(app, os.getenv("SLACK_API_TOKEN")).start()