'''
=================================================
ETL DAG for Car Sales Data
By: Fadhiil Dzaki Mulyana

ETL automation for extract data from Kaggle, cleaning & normalizing data, and load it to PostgreSQL.
=================================================
'''


# import libraries
from airflow import DAG
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.operators.python import PythonOperator
from datetime import datetime
import pandas as pd
from elasticsearch import Elasticsearch
import pendulum

# set local time
id_tz = pendulum.timezone("Asia/Jakarta")

#default parameter
default_args = {
    'owner' : 'fadhiil',
    'depens_on_past' : False,
    'email_on_failure' : False,
    'email_on_retry' : False,
    'retries' : 1,
    'start_date' : id_tz.datetime(2024,11,1)
}

# import data from postgres
def get_data(**context):
    '''
    Fungsi ini digunakan untuk mengambil data dari postgresql.
    '''
    # create connection
    source_hook = PostgresHook(postgres_conn_id='airflow_db')
    source_conn = source_hook.get_conn()
    source_cursor = source_conn.cursor()

    # read in pandas
    data_raw = pd.read_sql('SELECT * FROM table_m3', source_conn)

    # save df to csv (temporary)
    temp_file = '/tmp/raw_data.csv'
    data_raw.to_csv(temp_file, index=False)

    # push dile path to Xcom
    context['ti'].xcom_push(key='raw_data_path', value=temp_file)

# cleaning raw data
def cleaning_data(**context):
    '''
    Fungsi ini digunakan untuk melakukan cleaning data berupa merubah nama kolom menjadi lower case, spasi menjadi underscore,
    membuat kolom baru yang berisi unique identifier, merubah nama kolom holiday menjadi event, merubah value menjadi lowercase,
    drop duplicate, handling missing value dan merubah date menjadi datetime.
    '''
    # get task instance
    ti = context['ti']

    # get raw data
    temp_file = ti.xcom_pull(task_ids='get_data', key='raw_data_path')

    # transform to df
    data_raw = pd.read_csv(temp_file)

    # define categorical & numerical columns    
    # before
    print(data_raw)

    # cleaning process
    # lowercase column name
    data_raw.columns = data_raw.columns.str.lower()

    # replace space with underscore
    data_raw.columns = data_raw.columns.str.replace(' ', '_')

    # build unique identifier
    data_raw["code"] = data_raw["store_id"] + "-" + data_raw['category'].str[0] + "-" + data_raw["product_id"] + "-" + data_raw["date"].str.replace("-", "").str[2:8]

    # change column name
    data_raw = data_raw.rename(columns={'holiday/promotion' : 'event'})

    # value to lowercase
    for i in data_raw:
        if data_raw[i].dtype == 'object':
            data_raw[i] = data_raw[i].str.lower()

    # handling duplicate
    data_raw = data_raw.drop_duplicates(keep='last')

    # define id col
    id = ['store_id','product_id','date']

    # define categorical
    cat = ['store_id','product_id','category','region','weather_condition','event','seasonality']

    # loop handling missing value
    for i in data_raw.columns:
        # if i is an id column
        if i in id:
            # drop row
            data_raw[i] = data_raw[i].dropna()

        # if i is a primary key column
        elif i == 'code':
            # generate value
            data_raw['code'] = data_raw['store_id'] + '-' + data_raw['product_id'] + '-' + data_raw['date'].str.replace('-', '').str[2:8]

        # if i is a categorical column
        elif i in cat:
            # searc mode
            modus = data_raw[i].mode()[0]
            # fill with mode
            data_raw[i] = data_raw[i].fillna(modus)

        # if i is a numerical column
        else:
            # calculate median
            med = data_raw[i].median()
            # fill with median
            data_raw[i] = data_raw[i].fillna(med)

    # change date to datetime
    data_raw['date'] = pd.to_datetime(data_raw['date'])

    # clean data
    data_clean = data_raw.copy()

    # after
    print(data_clean)
    print(data_clean.info())

    # save df to csv (temporary)
    temp_file = '/tmp/clean_data.csv'
    data_clean.to_csv(temp_file, index=False)

    # save df to csv (local)
    save_file = '/opt/airflow/dags/P2M3_fadhiil_data_clean.csv'
    data_clean.to_csv(save_file, index=False)

    # push dile path to Xcom
    context['ti'].xcom_push(key='clean_data_path', value=temp_file)

# upload clean data to elastic
def upload_elastic(**context):
    '''
    Fungsi ini digunakan untuk melakukan upload data ke elasticsearch.
    '''
    # get task instance
    ti = context['ti']

    # get raw data
    temp_file = ti.xcom_pull(task_ids='cleaning_data', key='clean_data_path')

    # read data
    data_clean = pd.read_csv(temp_file)

    # LANJUTKAN CODE ELASTIC--
    # test ping
    es = Elasticsearch('http://elasticsearch:9200')

    # ingest data
    for i, r in data_clean.iterrows():
        doc = r.to_json()

        res = es.index(index='milestone_3', doc_type='doc', body=doc)


# DAG for otomation
with DAG(
    'Milestone_3_Fadhiil',
    description = 'import & clean raw data from PostgreSQL and upload it to ElasticSearch',
    schedule_interval = '10,20,30 9 * * 6',
    default_args = default_args,
    catchup = False
    ) as dag:

    # task 1: import raw data from postgres
    get = PythonOperator(
        task_id = 'get_data',
        python_callable = get_data,
        provide_context = True
    )

    # task 2: do data cleaning
    cleaning = PythonOperator(
        task_id = 'cleaning_data',
        python_callable = cleaning_data,
        provide_context = True
    )

    # task 3: upload cleaned data to elastic
    upload = PythonOperator(
        task_id = 'upload_elastic',
        python_callable = upload_elastic,
        provide_context=True
    )

get >> cleaning >> upload

