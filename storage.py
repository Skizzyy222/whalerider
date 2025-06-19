import json
import os

STORAGE_FILE = "subscribers.json"

def load_users():
    if not os.path.exists(STORAGE_FILE):
        return set()
    with open(STORAGE_FILE, "r") as f:
        try:
            return set(json.load(f))
        except:
            return set()

def save_users(users: set):
    with open(STORAGE_FILE, "w") as f:
        json.dump(list(users), f)

def add_user(user_id: int):
    users = load_users()
    users.add(user_id)
    save_users(users)

def remove_user(user_id: int):
    users = load_users()
    users.discard(user_id)
    save_users(users)
