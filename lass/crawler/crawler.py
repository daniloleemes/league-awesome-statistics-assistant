from pymongo import MongoClient
import requests
import threading
import time
import concurrent.futures
import sys
import os

thread_local = threading.local()
cls = lambda: os.system('clear')

api_key = ["RGAPI-885b0b9e-78c0-4383-82de-c03eec913f43", "RGAPI-da75265c-a919-4f4d-87d5-4c8dd1a9489f"]
base_url = "api.riotgames.com/lol"
leagues_uri = "league-exp/v4/entries"
summoners_uri = "summoner/v4/summoners"
matchlist_uri = "match/v4/matchlists/by-account"
match_uri = "match/v4/matches"
#regions = ['BR1', 'OC1', 'JP1', 'NA1', 'EUN1', 'EUW1', 'TR1', 'LA1', 'LA2', 'KR', 'RU']
regions = ['BR1', 'EUW1']
tiers = {
    'CHALLENGER': ['I'],
    'GRANDMASTER': ['I'],
    'MASTER': ['I'],
    'DIAMOND': ['I', 'II']
    # 'PLATINUM': ['I', 'II', 'III', 'IV'],
    # 'GOLD': ['I', 'II', 'III', 'IV'],
    # 'SILVER': ['I', 'II', 'III', 'IV'],
    # 'BRONZE': ['I', 'II', 'III', 'IV'],
    # 'IRON': ['I', 'II', 'III', 'IV']
}

console = {}

client = MongoClient('mongodb://localhost:27017/lass')
db = client.lass

def print_console():
    cls()
    for key in console:
        print(console[key])

def get_session():
    if not hasattr(thread_local, "session"):
        thread_local.session = requests.Session()
    return thread_local.session

def fetch_leagues(region):
    session = get_session()
    for tier in tiers:
        for rank in tiers[tier]:
            page = 1
            while True:
                url = f"https://{region}.{base_url}/{leagues_uri}/RANKED_SOLO_5x5/{tier}/{rank}?page={page}&api_key={api_key}"
                response = session.get(url).json()
                time.sleep(2)
                if len(response) == 0:
                    break
                else:
                    console[region] = f"{region} {tier} {rank} - PAGE {page}"
                    print_console()
                    for entry in response:
                        entry['region'] = region
                    db.leagues.insert_many(response)
                    page += 1
    console[region] = f"{region} FINISHED"
    print_console()
    fetch_summoners(region)

def fetch_summoners(region):
    session = get_session()
    print(f"Fetching summoners from {region}")
    count = db.leagues.count_documents({'region': region})
    cursor = db.leagues.find({'region': region})
    for i in range(count):
        entry = cursor[i]
        url = f"https://{region}.{base_url}/{summoners_uri}/{entry['summonerId']}?api_key={api_key}"
        response = session.get(url)
        time.sleep(2)
        if response.status_code == 200:
            summoner = response.json()
            summoner['region'] = region
            console[region] = f"{region} {i}/{count} SUMMONERS FETCHED"
            print_console()
            db.summoners.insert_one(summoner)
        else:
            print(f"Error fetching summoner {entry['summonerId']} from {region} with {response.status_code}")
    console[region] = f"{region} SUMMONERS FETCHED"
    print_console()
    fetch_matchlist(region)

def fetch_matchlist(region):
    session = get_session()
    pipeline = [
            {
                '$lookup': {
                    'from': 'matchlist', 
                    'localField': 'accountId', 
                    'foreignField': 'accountId', 
                    'as': 'remaining'
                }
            }, {
                '$match': {
                    'remaining': {
                        '$eq': []
                    },
                    'region': region
                }
            }
        ]
    cursor = db.summoners.aggregate(pipeline)
    print(cursor.explain())
    for i in len(cursor):
        begin_index = 0
        url = f"https://{region}.{base_url}/{matchlist_uri}/{summoner['accountId']}?api_key={api_key}&beginIndex={begin_index}&queue=420"
        response = session.get(url)
        time.sleep(2)
        
        if response.status_code == 200:
            matchlist = {**response.json(), "accountId": summoner['accountId']}
            db.matchlist.insert_one(matchlist)
        console[region] = f"{region} {i}/{cursor.count_documents()} MATCHLIST FETCHED"
        print_console()
    console[region] = f"{region} MATCHLISTS FETCHED"
    print_console()
    clean_matchlists(region)

def fetch_remaining_matchlists(summoners):
    session = get_session()
    region = ''
    count = len(summoners)
    for i in range(count):
        summoner = summoners[i]
        begin_index = 0
        region = summoner['region']
        url = f"https://{region}.{base_url}/{matchlist_uri}/{summoner['accountId']}?api_key={api_key[i % len(api_key)]}&beginIndex={begin_index}&queue=420"
        response = session.get(url)

        if response.status_code == 200:
            matchlist = {**response.json(), "accountId": summoner['accountId']}
            db.matchlist.insert_one(matchlist)
        else:
            print("Could not execute request")
        console[region] = f"{region} {i}/{count} MATCHLIST FETCHED"
        print_console()
        time.sleep(1)
    console[region] = f"{region} MATCHLISTS FETCHED"
    print_console()
    clean_matchlists(region)

def fetch_remaining_summoners(entries):
    session = get_session()
    count = len(entries)
    region = entries[0]['region']
    for i in range(count):
        entry = entries[i]
        url = f"https://{region}.{base_url}/{summoners_uri}/{entry['summonerId']}?api_key={api_key}"
        response = session.get(url)
        time.sleep(2)
        if response.status_code == 200:
            summoner = { **response.json(), "region": region }
            db.summoners.insert_one(summoner)
        console[region] = f"{region} {i}/{count} SUMMONERS FETCHED"
        print_console()
    console[region] = f"{region} SUMMONERS FETCHED"
    print_console()

def clean_matchlists():
    for region in regions:
        console[region] = f"{region} CLEANING MATCHLISTS"
        print_console()
        pipeline = [
            {
                '$lookup': {
                    'from': 'summoners', 
                    'localField': 'accountId', 
                    'foreignField': 'accountId', 
                    'as': 'summoner'
                }
            }, {
                '$unwind': {
                    'path': '$summoner'
                }
            }, {
                '$project': {
                    '_id': 1, 
                    'matches': 1, 
                    'accountId': 1, 
                    'region': '$summoner.region'
                }
            }, {
                '$match': {
                    'region': region
                }
            }
        ]
        matchlist = [match['matches'] for match in db.matchlist.aggregate(pipeline)]
        matches = [{"gameId":item['gameId'], "platformId": item['platformId']} for sublist in matchlist for item in sublist]
        matches_filtered = [dict(y) for y in set(tuple(x.items()) for x in matches)]
        console[region] = f"{region} {len(matches_filtered)} MATCHES WILL BE INSERTED"
        print_console()
        for match in matches_filtered:
            try:
                db.matches.insert_one(match)
            except:
                print(f"{match} NOT INSERTED")

def fetch_matches(region):
    console[region] = f"{region} FETCHING MATCHES"
    print_console()
    session = get_session()
    count = db.matches.count_documents({'platformId': region, 'seasonId': { "$exists": False }})
    cursor = db.matches.find({'platformId': region, 'seasonId': { "$exists": False }})
    for i in range(count):
        match = cursor[i]
        key = api_key[i % len(api_key)]
        url = f"https://{region}.{base_url}/{match_uri}/{match['gameId']}?api_key={key}"
        response = session.get(url)

        if response.status_code == 200:
            db.matches.update_one({"_id": match['_id']}, { "$set": { **response.json() }})
            console[region] = f"{region} {i}/{count} MATCHES FETCHED [{key}]"
            print_console()
        else: 
            console[region] = f"{region} {i}/{count} MATCHES FETCHED [ERROR]"
            print_console()
            time.sleep(10)
        

def crawl_regions():
    with concurrent.futures.ThreadPoolExecutor(max_workers=11) as executor:
        executor.map(fetch_leagues, regions)


def crawl_summoners():
    with concurrent.futures.ThreadPoolExecutor(max_workers=11) as executor:
        executor.map(fetch_summoners, regions)


def crawl_matchlists():
    with concurrent.futures.ThreadPoolExecutor(max_workers=11) as executor:
        executor.map(fetch_matchlist, regions)


def crawl_matches():
    with concurrent.futures.ThreadPoolExecutor(max_workers=11) as executor:
        executor.map(fetch_matches, regions)


def crawl_remaining_matchlists():
    summoners = []
    for region in regions:
        pipeline = [
            {
                '$lookup': {
                    'from': 'matchlist', 
                    'localField': 'accountId', 
                    'foreignField': 'accountId', 
                    'as': 'remaining'
                }
            }, {
                '$match': {
                    'remaining': {
                        '$eq': []
                    },
                    'region': region
                }
            }
        ]
        summoners.append(list(db.summoners.aggregate(pipeline)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=11) as executor:
        executor.map(fetch_remaining_matchlists, summoners)

def crawl_remaining_summoners():
    summoners = []
    for region in regions:
        pipeline = [
            {
                '$lookup': {
                    'from': 'summoners', 
                    'localField': 'summonerId', 
                    'foreignField': 'id', 
                    'as': 'remaining'
                }
            }, {
                '$match': {
                    'remaining': {
                        '$eq': []
                    },
                    'region': region
                }
            }
        ]
        summoners.append(list(db.leagues.aggregate(pipeline)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=11) as executor:
        executor.map(fetch_remaining_matchlists, summoners)


if __name__ == "__main__":
    try:
        # crawl_regions()
        # crawl_summoners()
        # crawl_matchlists()
        # clean_matchlists()
        crawl_matches()
        # crawl_remaining_summoners()
        # crawl_remaining_matchlists()
    except KeyboardInterrupt:
        sys.exit()
