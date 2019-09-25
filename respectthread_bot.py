import praw         # Interface with Reddit's API
import psycopg2     # Interface with PostgreSQL
import config       # Login details
import time         # To make an interval for the bot to wait
import os           # To check if a file exists
import re           # Regular expressions
import unicodedata  # To strip accents

subreddit_list = ["test"]
posts_list = []
blacklist = []
respectthread_list = []

class Character:
    def __init__(self, name, default_name, version, respectthreads):
        self.name = name
        self.default_name = default_name
        self.version = version
        self.respectthreads = respectthreads

def bot_login():
    print("Logging in...")
    r = praw.Reddit(username = config.r_username,
                password = config.r_password,
                client_id = config.client_id,
                client_secret = config.client_secret,
                user_agent = "respectthread responder v0.2")
    print("Logged in")
    if posts_list[-1] != "":
        with open("saved_posts.txt", "a") as f:
            f.write('\n')
    return r

def get_saved_posts():
    # Make sure the file exists.
    if not os.path.isfile("saved_posts.txt"):
        posts_list = []
    else:
        # "r" is to read from saved_posts.txt as the variable f
        with open("saved_posts.txt", "r") as f:
            posts_list = f.read().split("\n")
    return posts_list

def get_blacklist():
    if not os.path.isfile("blacklist.txt"):
        blacklist = []
    else:
        with open("blacklist.txt", "r") as f:
            blacklist = f.read().split("\n")
    return blacklist

def run_bot(r):
    print("Connecting to database...")
    con = psycopg2.connect(
        host = config.host,
        database = config.database,
        user = config.d_user,
        password = config.d_password
    )
    print("Connected to database")
    cur = con.cursor()

    for sub in subreddit_list:
        print("Obtaining new posts from r/{}".format(sub))
        submissions = r.subreddit(sub).new(limit=7)
        for submission in submissions:
            if submission.id not in posts_list and submission.author.name not in blacklist:
                title = strip_accents(submission.title)
                post = title + " " + strip_accents(submission.selftext)
                character_list = search_characters(title, post, cur)
                if character_list:
                    generate_reply(submission, cur, character_list)

    # Close the cursor and connection
    cur.close()
    con.close()
    print("Disconnected from database")
    sleep_time = 30
    print("Sleeping for {} seconds...".format(sleep_time))
    time.sleep(sleep_time)

def search_characters(title, post, cur):
    character_list = []
    characters_checked = []
    respectthread_list.clear()
    cur.execute("SELECT * FROM character_name ORDER BY is_team DESC, length(name) DESC;")
    names = cur.fetchall()
    for n in names:
        found_char = False
        name = n[0]
        default_name = n[1]
        if default_name not in characters_checked and post_contains(name, post, cur):
            found_char = True
            char_added = False
            cur.execute("SELECT * FROM character WHERE default_name = '{}' ORDER BY is_default;".format(default_name))
            characters = cur.fetchall()
            for c in characters:
                version = c[1]
                respectthread_ids = c[3]
                verse_name = c[4]
                if check_version_array(version, post, cur):                                                             # Check if the post contains the character's verse-name
                    add_character(name, default_name, verse_name, respectthread_ids, title, post, cur, character_list)
                    char_added = True

            if not char_added:                                                                                          # If the post doesn't mention the character's version,
                for c in characters:                                                                                    # use the default version
                    is_default = c[2]
                    if is_default:
                        add_character(name, default_name, c[4], c[3], title, post, cur, character_list)

        if found_char:                                                                                                  # Prevents redundant character checks
            characters_checked.append(default_name)
    return character_list

def check_version_array(version, post, cur):
    for string in version:
        if not post_contains(string, post, cur):
            return False
    return True

def post_contains(name, post, cur):
    regex = re.compile(r"\b%s\b" % name, re.IGNORECASE)
    if re.search(regex, post) is not None:
        cur.execute("SELECT COUNT(*) FROM name_conflict WHERE LOWER(name) = '{}'".format(name.lower()))
        row_count = cur.fetchone()[0]
        if row_count == 0:
            return True
        else:
            cur.execute("SELECT conflict, first_char FROM name_conflict WHERE LOWER(name) = '{}'".format(name.lower()))  # For all matches, check if the name doesn't mean something else
            rows = cur.fetchall()
            name_locations = [m.start() for m in re.finditer(regex, post)]
            for n in name_locations:
                non_matches = 0
                for row in rows:
                    conflict = row[0].lower()
                    first_char = n + row[1]
                    last_char = first_char + len(conflict)
                    substring = post[first_char : last_char].lower()
                    if substring != conflict:
                        non_matches += 1
                if non_matches == row_count:
                    return True
    return False

def strip_accents(text):
    try:
        text = unicode(text, 'utf-8')
    except NameError: # unicode is a default on python 3
        #print("NameError")
        pass

    text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode("utf-8")
    return str(text)

def add_character(name, default_name, verse_name, respectthread_ids, title, post, cur, character_list):
    if post_contains(default_name, title, cur):                                                                         # The bot prefers names found in the title
        add_to_reply(default_name, default_name, verse_name, respectthread_ids, character_list, post, cur)              # and prefers the character's "default name"
    elif post_contains(name, title, cur):
        name = extract_match(name, title)
        add_to_reply(name, default_name, verse_name, respectthread_ids, character_list, post, cur)
    elif post_contains(default_name, post, cur):
        add_to_reply(default_name, default_name, verse_name, respectthread_ids, character_list, post, cur)
    else:
        name = extract_match(name, post)
        add_to_reply(name, default_name, verse_name, respectthread_ids, character_list, post, cur)

def extract_match(name, post):
    regex = re.compile(r"\b{}\b".format(name), re.IGNORECASE)
    return re.search(regex, post).group(0)

def add_to_reply(name, default_name, verse_name, respectthread_ids, character_list, post, cur):
    included_rts = []
    for id in respectthread_ids:
        if is_rt_in_post(id, post, cur):
            respectthread_list.append(id)
        if id not in respectthread_list:
            respectthread_list.append(id)                                                                               # To prevent linking duplicates
            included_rts.append(id)

    if included_rts:
        character_list.append(Character(name, default_name, verse_name, included_rts))

def is_rt_in_post(id, post, cur):                                                                                       # Check if the post already linked that RT
    cur.execute("SELECT link FROM respectthread WHERE id = {} LIMIT 1;".format(id))
    link = cur.fetchone()[0]
    regex = re.compile(r"https://redd\.it/([a-zA-A0-9]{6})")
    match_shortlink = regex.search(link)
    if match_shortlink is not None:
        post_id = match_shortlink.group(1)
        regex = re.compile(r"\b{}\b".format(post_id))
        if re.search(regex, post) is not None:
            return True
    else:
        regex = re.compile(r"comments/([a-zA-A0-9]{6})")
        match_permalink = regex.search(link)
        if match_permalink is not None:
            post_id = match_permalink.group(1)
            regex = re.compile(r"\b{}\b".format(post_id))
            if re.search(regex, post) is not None:
                return True
    return False

def generate_reply(submission, cur, character_list):
    reply_text = ""
    sorted_list = sorted(character_list, key = lambda character: (character.default_name, character.version))

    for character in sorted_list:
        if character.respectthreads:
            reply_text += "**" + character.name
            if character.version != "":
                reply_text += " ({})".format(character.version)
            reply_text += "**\n\n"
            rt_query = "SELECT c.* FROM respectthread c JOIN (VALUES "
            for i in range(len(character.respectthreads)):
                rt_query += "({}, {}),".format(character.respectthreads[i], i)
            rt_query = rt_query.rstrip(",")
            rt_query += ") AS x (id, ordering) ON c.id = x.id ORDER BY x.ordering;"
            cur.execute(rt_query)
            respectthreads = cur.fetchall()
            for row in respectthreads:
                reply_text += "- [{}]({})\n\n".format(row[1], row[2])

    if reply_text != "":
        submission.reply(reply_text)
        print(reply_text)
    with open("saved_posts.txt", "a") as f:
        f.write(submission.id + '\n')
    posts_list.append(submission.id)

terminate_time = 40
posts_list = get_saved_posts()
blacklist = get_blacklist()
r = bot_login()
while True:
    run_bot(r)
    terminate_time -= 1
    if terminate_time <= 0:
        exit()
