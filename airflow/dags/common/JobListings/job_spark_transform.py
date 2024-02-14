from job_spark_session_manager import JobSparkSessionManager
from job_s3_client_manager import JobS3ClientManager
from job_file_processing import JobFileProcessing
from job_data_storage import JobDataStorage
from job_data_transformation import JobDataTransformation
from job_data_enrichment import JobDataEnrichment
from job_config_manager import JobConfigManager

from pyspark.sql.functions import col
from pyspark.sql import DataFrame
import os
import yaml

# from airflow.exceptions import AirflowFailException
import logging
import sys
import socket

import re


def to_snake_case(name):
    # Zuerst von CamelCase/PascalCase zu snake_case
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower() + "_df"


def is_dataframe_empty(df: DataFrame) -> bool:
    """Check if a DataFrame is empty."""
    return df.count() == 0


if __name__ == "__main__":
    args = sys.argv
    appname = args[1]
    source_name = args[2]
    bucket_from = args[3]
    bucket_to = args[4]
    delta_minutes = int(args[5])

    spark_manager = JobSparkSessionManager(appname)
    spark_session = spark_manager.get_spark_session()

    # setup logger
    spark_session.sparkContext.setLogLevel("ERROR")
    log4jLogger = spark_session._jvm.org.apache.log4j
    logger = log4jLogger.LogManager.getLogger("LOGGER")
    logger.setLevel(log4jLogger.Level.INFO)

    AWS_SPARK_ACCESS_KEY = os.getenv('MINIO_SPARK_ACCESS_KEY')
    AWS_SPARK_SECRET_KEY = os.getenv('MINIO_SPARK_SECRET_KEY')
    MINIO_IP_ADDRESS = socket.gethostbyname("minio")
    SPARK_MASTER_IP_ADDRESS = socket.gethostbyname("spark-master")

    s3_client_manager = JobS3ClientManager(
        AWS_SPARK_ACCESS_KEY, AWS_SPARK_SECRET_KEY, f"http://{MINIO_IP_ADDRESS}:9000")
    s3_client = s3_client_manager.get_boto_client()

    file_processor = JobFileProcessing(
        s3_client, bucket_from, source_name, delta_minutes)

    data_storage = JobDataStorage()

    data_transformation = JobDataTransformation(args)
    data_enrichment = JobDataEnrichment(spark_session)

    # Der Hauptablauf würde hier folgen, z.B.:
    data_raw = file_processor.load_recent_files()

    schema = data_transformation.get_df_schema(source_name)
    spark_df = spark_session.createDataFrame(data_raw, schema=schema)

    data_clean_df = data_transformation.transform(spark_df)

    # Create the Dim DataFrames
    # index,company_name,company_linkedin_url,title,location,linkedin_id,url,applicants,publish_date,level,employment,function,industries,description,search_datetime,search_keyword,search_location,fingerprint,language

    # combining the unique date values
    date_df1 = data_clean_df.select(
        col("publish_date_unique").alias("date_unique"))
    date_df2 = data_clean_df.select(
        col("search_datetime_unique").alias("date_unique"))
    date_df = date_df1.union(date_df2)

    dataframes = {
        "dim_jobs_df": data_clean_df.select(
            "title", "title_cleaned", "description", "source_identifier", "fingerprint"),
        "dim_locations_df": data_clean_df.select(
            col("location").alias("city"), "country"),  # country is not there yet!
        "dim_languages_df": data_clean_df.select(col("language").alias("name")),
        "dim_sources_df": data_clean_df.select(
            col("source").alias("name")),  # source is not there
        "dim_job_levels_df": data_clean_df.select(col("level").alias("name")),
        "dim_search_keywords_df": data_clean_df.select(
            col("search_keyword").alias("name")),
        "dim_search_locations_df": data_clean_df.select(
            col("search_location").alias("name")),
        # "dim_dates_df": data_clean_df.select(),
        "dim_dates_df": date_df,
        "dim_employments_df": data_clean_df.select(col("employment").alias("name")),
        "dim_industries_df": data_clean_df.select(col("industries").alias("name")),
        # "dim_skill_categories_df": data_clean_df.select(),
        # "dim_technology_categories_df": data_clean_df.select(),
        # "dim_skills_df": data_clean_df.select(),
        # "dim_technologies_df": data_clean_df.select(),
        "dim_companies_df": data_clean_df.select(col("company_name").alias("name"))
    }

    fact_df = data_clean_df.select("company_name", "title", "location", "job_apps_count", "level", "employment",
                                   "industries", "search_datetime", "search_keyword", "search_location", "fingerprint", "language", "scrape_dur_ms",
                                   "publish_date_unique", "publish_date_year", "publish_date_month", "publish_date_week", "publish_date_day", "publish_date_hour", "publish_date_minute", "publish_date_week_day", "publish_date_is_holiday",
                                   "search_datetime_unique", "search_datetime_year", "search_datetime_month", "search_datetime_week", "search_datetime_day", "search_datetime_hour", "search_datetime_minute", "search_datetime_week_day", "search_datetime_is_holiday")

    # load config
    dimensions_info = JobConfigManager.load_config(
        "job_config.yaml", "dimensions_info")

    # Loop through each dimension table and perform the enrichment
    for dim_table, info in dimensions_info.items():
        logger.info(f"Start working on {dim_table}")
        # Determine the DataFrame name based on the key
        dataframe_name = to_snake_case(dim_table)

        # Determine the dimIdColumn if not provided or empty
        if not info.get("dimIdColumn"):
            info["dimIdColumn"] = data_enrichment.generate_dim_id_column_name(
                dim_table)

        # Access the corresponding DataFrame
        dim_df = dataframes.get(dataframe_name)
        if not dim_df:
            raise ValueError(f"DataFrame {dataframe_name} not found")

        # Load existing data from the dimension table
        dim_existing_df = data_enrichment.load_dimension_table(
            dim_table, info.get("distinctColumns"))

        # Identify new values by comparing with existing data
        dim_new_values_df = dim_df.select(
            info.get("distinctColumns")).distinct().exceptAll(dim_existing_df)

        # # If there are new values, save them to the dimension table
        # if not is_dataframe_empty(dim_new_values_df):
        #     data_enrichment.save_dimension_table(dim_new_values_df, dim_table)
        #     # Reload the dimension table to include the newly added values
        #     dim_existing_df = data_enrichment.load_dimension_table(dim_table)

        # # Perform the join to enrich the fact dataframe
        # fact_df = fact_df.join(dim_existing_df, fact_df[info["factColumn"]] == dim_existing_df[info["dimColumn"]], "left") \
        #     .withColumn(info["factForeignKeyColumn"], dim_existing_df[info["dimIdColumn"]])

        # save the dim tables
        if not is_dataframe_empty(dim_new_values_df):
            logger.info(f"Start saving {dim_table}")
            target_path_delta = f"s3a://{bucket_to}/{source_name}/delta/{dim_table}"
            target_path_csv = f"s3a://{bucket_to}/{source_name}/csv/{dim_table}"

            data_storage.save_from_spark_as_delta(
                dim_new_values_df, target_path_delta)
            data_storage.save_from_spark_as_csv(
                dim_new_values_df, target_path_csv)
            logger.info(f"Done saving {dim_table}")

    # save the fact table
    if not is_dataframe_empty(fact_df):
        logger.info(f"Start saving Fact Table")
        target_path_delta = f"s3a://{bucket_to}/{source_name}/delta/fctJobListings"
        target_path_csv = f"s3a://{bucket_to}/{source_name}/csv/fctJobListings"

        data_storage.save_from_spark_as_delta(fact_df, target_path_delta)
        data_storage.save_from_spark_as_csv(fact_df, target_path_csv)
        logger.info(f"Done saving Fact Table")

    spark_manager.stop()
