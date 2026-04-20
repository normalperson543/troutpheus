import os
import time
import datetime
from peewee import *
from playhouse.postgres_ext import *
from slack_bolt import App
from slack_sdk import WebClient
from dotenv import load_dotenv


load_dotenv()
app = App(token=os.getenv("SLACK_BOT_TOKEN"))

client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))

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
    
print("Connecting to database")
db.connect()
print("Done")

users = User.select()

for user in users:
    print(f"Getting info for {user.user_id}")
    slack_user = client.users_info(user=user.user_id)
    try:
      real_name = slack_user["user"]["real_name"]
      print(f"Real name is {real_name}")
      user.username = slack_user["user"]["real_name"]
      user.save()
    except KeyError:
      print(f"Could not find the real name for {user.user_id}")
      print(slack_user["user"])
    time.sleep(2)