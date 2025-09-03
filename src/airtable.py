import os
from pyairtable import Api
from dotenv import load_dotenv
load_dotenv()

# Airtable config
AIRTABLE_PAT = os.getenv("AIRTABLE_PAT")
BASE_ID =  os.getenv("AIRTABLE_BASE_ID", "appdKQ8h63VIsBEAj")  # Replace with your base ID
DATA_TABLE_NAME = os.getenv("DATA_TABLE_ID", "tiktok")
HASHTAGS_TABLE_NAME = os.getenv("HASHTAG_TABLE_ID", "hashtags")

api = Api(AIRTABLE_PAT)
data_table = api.table(BASE_ID, DATA_TABLE_NAME)
hashtags_table = api.table(BASE_ID, HASHTAGS_TABLE_NAME)
print("Connected to Airtable Table:", data_table.name)
print("Connected to Hashtags Table:", hashtags_table.name)


def save_profile_to_airtable(profile_data: dict):
    """
    Save a scraped profile to Airtable.
    
    profile_data: {
        "Name": str,
        "Username": str,
        "Followers": int,
        "Profile URL": str,
        ...
    }
    """
    try:
        record = data_table.create(profile_data)
        print(f"✅ Saved to Airtable: {profile_data['Username']}")
        return record
    except Exception as e:
        print(f"❌ Error saving to Airtable: {e}")
        return None
    
def get_existing_usernames():
    """
    Fetch all usernames from the Airtable table.
    Returns a Python list of usernames.
    """
    # Fetch all records
    records = data_table.all()    
    # Extract Username field values
    usernames = []
    for record in records:
        username = record["fields"].get("Username")
        if username:  # avoid None values
            usernames.append(username)   
    return usernames

def get_active_hashtags():
    """
    Fetch all active hashtags from the hashtags table.
    Only returns hashtags where Active field is True/checked.
    
    Returns:
        list: List of active hashtag strings
    """
    try:
        # Fetch all records from hashtags table
        records = hashtags_table.all()
        # Filter for only active hashtags
        active_hashtags = []
        for record in records:
            fields = record["fields"]
            hashtag = fields.get("Hashtag").lower()
            is_active = fields.get("Active", False)
            
            # Only include hashtags that are active (True/checked)
            if hashtag and is_active:
                active_hashtags.append(hashtag)
        
        print(f"✅ Fetched {len(active_hashtags)} active hashtags from Airtable")
        return active_hashtags
        
    except Exception as e:
        print(f"❌ Error fetching hashtags from Airtable: {e}")
        return []

if __name__ == "__main__":
#     from schemas import Profile
#     # Example profile data
#     profile = Profile(
#     Username="John Doe",
#     Bio="@johndoe",
#     Followers=48700,
#     Likes=9818,
#     Profile_URL="https://www.tiktok.com/@johndoe",
#     Image_URL="https://example.com/image.jpg",
#     Hashtag=", ".join(["travel", "funnyvideos"]),   # Multiple hashtags
#     Blacklist=False,
#     Source="Tiktok",
#     Country="USA"
# )
#     save_profile_to_airtable(profile.model_dump())
    hashtags = get_active_hashtags()
    print(f"✅ Fetched {len(hashtags)} active hashtags from Airtable")
    for hashtag in hashtags:
        print(hashtag)