from pymongo import MongoClient
from typing import List, Optional
from datetime import datetime, timedelta
# from app.config.constants import COLLECTIONS, MONGO, FIELDS, MISC
from config.constants import COLLECTIONS, MONGO, FIELDS, MISC

class DbQuery:
    def __init__(self, uri: str = MONGO["uri"], database_name: str = MONGO["db"], collection_name: str = COLLECTIONS["all"]):
        # print(uri)
        # print(database_name)
        # print(collection_name)
        self.client = MongoClient(uri)
        # self.uri = uri
        # self.database = self.client[database_name]
        # self.collection = self.database[collection_name]
        # self.client = MongoClient('mongodb://localhost:27017/')
        self.uri = uri
        self.database = self.client[database_name]
        self.collection = self.database[collection_name]

    def query_jobs(self, keyword: Optional[str] = None, level: Optional[str] = None,
                   location: Optional[str] = None, age: Optional[int] = None,
                   order: str = 'asc', page: int = 1, items_per_page: int = MISC["items_per_page"]) -> List[dict]:
        query = {}

        # print(self.calculate_date_from_age(age))
        '''
        if keyword:
            query[FIELDS["description"]] = {"$regex": keyword, "$options": "i"}


        if age:
            query[FIELDS["publish_date"]] = {"$gte": self.calculate_date_from_age(age)}
        '''

        # if level:
        #     query[FIELDS["level"]] = self.map_level(level)
        if level:
            if isinstance(level, list):
                query[FIELDS["level"]] = {"$in": [lev for lev in level]}
            else:
                query[FIELDS["level"]] = level

        # if location:
        #     query[FIELDS["location"]] = location
        if location:
            if isinstance(location, list):
                query[FIELDS["location"]] = {"$in": [loc for loc in location]}
            else:
                query[FIELDS["location"]] = location


        # Sort order
        # sort_order = pymongo.ASCENDING if order == 'asc' else pymongo.DESCENDING
        sort_order = 1 if order == 'asc' else -1

        # Calculate skip and limit for pagination
        offset = (page - 1) * items_per_page
        limit = items_per_page

        # Perform the query
        result = self.collection.find(query, {"_id": 0}).sort(FIELDS["publish_date"], sort_order).skip(offset).limit(limit)
        # result = self.collection.find({}, {"_id": 0}).sort(FIELDS["publish_date"], sort_order).skip(offset).limit(limit)

        # Convert query result to a list of dictionaries
        job_list = list(result)
        print(len(job_list))

        # print(self.uri)
        # print(self.database)
        # print(self.collection)

        return job_list

    def calculate_date_from_age(self, age_in_days: int) -> datetime:
        current_date = datetime.now()
        calculated_date = current_date - timedelta(days=age_in_days)
        return calculated_date

    def close_connection(self):
        self.client.close()

