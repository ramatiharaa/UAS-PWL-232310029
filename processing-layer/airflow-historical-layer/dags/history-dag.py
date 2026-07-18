from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from kafka import KafkaConsumer
import json
import pandas as pd
from psycopg2.extras import execute_values
import pytz
import logging

KAFKA_BROKER = 'kafka:29092'
KAFKA_TOPIC = 'traffic-data-topic'
WINDOW_MINUTES = 60
TIMEZONE = 'Asia/Jakarta'
BATCH_SIZE = 20000
LOG = logging.getLogger(__name__)

def consume_from_kafka(**context):
    try:
        consumer = KafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=KAFKA_BROKER,
            group_id='airflow-summary-group',
            auto_offset_reset='earliest',
            value_deserializer=lambda x: json.loads(x.decode('utf-8')),
            consumer_timeout_ms=30000
        )

        messages = []
        for msg in consumer:
            messages.append(msg.value)
            if len(messages) >= BATCH_SIZE:
                LOG.info(f"Mencapai batas maksimal batch {BATCH_SIZE} pesan demi keamanan RAM.")
                break
                
        consumer.close()
        LOG.info(f" Berhasil consume {len(messages)} messages dari Kafka")

        context['ti'].xcom_push(key='messages', value=messages)
        context['ti'].xcom_push(key='messages_count', value=len(messages))
        return len(messages)
        
    except Exception as e:
        LOG.error(f" Error consuming from Kafka: {e}")
        context['ti'].xcom_push(key='messages', value=[])
        context['ti'].xcom_push(key='messages_count', value=0)
        return 0


def transform_and_aggregate(**context):
    ti = context['ti']
    messages = ti.xcom_pull(key='messages', task_ids='consume_kafka')
    messages_count = ti.xcom_pull(key='messages_count', task_ids='consume_kafka')

    if not messages or messages_count == 0:
        LOG.warning("Tidak ada data untuk diagregasi")
        return "No data"

    LOG.info(f"Memproses {len(messages)} messages")

    df = pd.DataFrame(messages)
    LOG.info(f"Jumlah baris awal: {len(df)}")
    
    required_columns = ['source_id', 'tracker_id', 'vehicle_type', 'speed_kmh', 'timestamp']
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        LOG.error(f"Kolom yang hilang: {missing_cols}")
        return "Missing columns"
    
    df = df.dropna(subset=required_columns)
    LOG.info(f"Setelah drop NaN: {len(df)} baris")
    
    df = df[df['speed_kmh'] > 0]
    df = df[df['speed_kmh'] < 150]
    LOG.info(f"Setelah filter speed: {len(df)} baris")
    
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    if df['timestamp'].dt.tz is None:
        df['timestamp_wib'] = df['timestamp'].dt.tz_localize(TIMEZONE)
    else:
        df['timestamp_wib'] = df['timestamp'].dt.tz_convert(TIMEZONE)
        
    df['window_start'] = df['timestamp_wib'].dt.floor(f'{WINDOW_MINUTES}min')
    
    LOG.info(f"Rentang waktu: {df['window_start'].min()} - {df['window_start'].max()}")
    
    vehicle_level = (
        df.groupby(['window_start', 'source_id', 'tracker_id'])
        .agg(
            vehicle_type=('vehicle_type', lambda x: x.mode().iloc[0] if not x.empty else 'unknown'),
            avg_speed=('speed_kmh', 'mean'),
            count_observations=('speed_kmh', 'count'),
            min_speed=('speed_kmh', 'min'),
            max_speed=('speed_kmh', 'max'),
        )
        .reset_index()
    )
    
    LOG.info(f"Total kendaraan unik (source_id + tracker_id): {len(vehicle_level)}")
    
    for source_id in vehicle_level['source_id'].unique():
        source_data = vehicle_level[vehicle_level['source_id'] == source_id]
        unique_trackers = source_data['tracker_id'].nunique()
        total_obs = source_data['count_observations'].sum()
        LOG.info(f"{source_id}: {unique_trackers} kendaraan unik, {total_obs} observasi")
    
    total_summary = []
    for (window_start, source_id), group in vehicle_level.groupby(['window_start', 'source_id']):
        total_summary.append({
            'window_start': window_start.strftime('%Y-%m-%d %H:%M:%S'),
            'window_end': (window_start + pd.Timedelta(minutes=WINDOW_MINUTES)).strftime('%Y-%m-%d %H:%M:%S'),
            'source_id': source_id,
            'total_vehicles': int(len(group)),
            'avg_speed_kmh': round(float(group['avg_speed'].mean()), 2),
        })

    type_summary = []
    by_type = (
        vehicle_level.groupby(['window_start', 'source_id', 'vehicle_type'])
        .agg(
            vehicle_count=('tracker_id', 'count'),
            avg_speed=('avg_speed', 'mean'),
            avg_observations=('count_observations', 'mean'),
        )
        .reset_index()
    )
    
    for _, row in by_type.iterrows():
        window_start = row['window_start']
        type_summary.append({
            'window_start': window_start.strftime('%Y-%m-%d %H:%M:%S'),
            'window_end': (window_start + pd.Timedelta(minutes=WINDOW_MINUTES)).strftime('%Y-%m-%d %H:%M:%S'),
            'source_id': row['source_id'],
            'vehicle_type': row['vehicle_type'],
            'vehicle_count': int(row['vehicle_count']),
            'avg_speed_kmh': round(float(row['avg_speed']), 2),
            'avg_observations_per_vehicle': round(float(row['avg_observations']), 2),
        })

    LOG.info(f"Total summary: {len(total_summary)} windows, breakdown tipe: {len(type_summary)} baris")
    
    for summary in total_summary:
        LOG.info(f"{summary['source_id']} {summary['window_start']}: {summary['total_vehicles']} kendaraan, avg {summary['avg_speed_kmh']} km/h")
    
    ti.xcom_push(key='total_summary', value=total_summary)
    ti.xcom_push(key='type_summary', value=type_summary)
    ti.xcom_push(key='unique_vehicles', value=len(vehicle_level))
    
    return len(total_summary)


def load_summary_to_postgres(**context):
    ti = context['ti']
    total_summary = ti.xcom_pull(key='total_summary', task_ids='transform_data')
    type_summary = ti.xcom_pull(key='type_summary', task_ids='transform_data')
    messages_count = ti.xcom_pull(key='messages_count', task_ids='consume_kafka')
    unique_vehicles = ti.xcom_pull(key='unique_vehicles', task_ids='transform_data')

    if not total_summary:
        LOG.warning("Tidak ada summary untuk di-load")
        return "No data to load"

    LOG.info(f"Memuat {len(total_summary)} baris ke database")

    pg_hook = PostgresHook(postgres_conn_id='postgres_default')
    conn = pg_hook.get_conn()
    cursor = conn.cursor()

    try:
        cursor.execute("SET timezone = 'Asia/Jakarta';")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS rep_traffic_summary_5min (
            id                SERIAL PRIMARY KEY,
            window_start      TIMESTAMP NOT NULL,
            window_end        TIMESTAMP NOT NULL,
            source_id         VARCHAR(50) NOT NULL,
            total_vehicles    INTEGER   NOT NULL DEFAULT 0,
            avg_speed_kmh     FLOAT,
            created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_rep_traffic_summary_window UNIQUE (window_start, source_id)
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS rep_traffic_summary_5min_by_type (
            id                SERIAL PRIMARY KEY,
            window_start      TIMESTAMP NOT NULL,
            window_end        TIMESTAMP NOT NULL,
            source_id         VARCHAR(50) NOT NULL,
            vehicle_type      VARCHAR(50) NOT NULL,
            vehicle_count     INTEGER   NOT NULL DEFAULT 0,
            avg_speed_kmh     FLOAT,
            created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_rep_traffic_summary_type_window UNIQUE (window_start, source_id, vehicle_type)
        );
        """)

        total_values = [
            (row['window_start'], row['window_end'], row['source_id'],
             row['total_vehicles'], row['avg_speed_kmh'])
            for row in total_summary
        ]
        
        execute_values(cursor, """
            INSERT INTO rep_traffic_summary_5min
            (window_start, window_end, source_id, total_vehicles, avg_speed_kmh)
            VALUES %s
            ON CONFLICT ON CONSTRAINT uq_rep_traffic_summary_window DO UPDATE SET
                window_end = EXCLUDED.window_end,
                total_vehicles = EXCLUDED.total_vehicles,
                avg_speed_kmh = EXCLUDED.avg_speed_kmh;
        """, total_values)
        
        LOG.info(f"Inserted {len(total_values)} records to rep_traffic_summary_5min")

        if type_summary:
            type_values = [
                (row['window_start'], row['window_end'], row['source_id'],
                 row['vehicle_type'], row['vehicle_count'], row['avg_speed_kmh'])
                for row in type_summary
            ]
            
            execute_values(cursor, """
                INSERT INTO rep_traffic_summary_5min_by_type
                (window_start, window_end, source_id, vehicle_type, vehicle_count, avg_speed_kmh)
                VALUES %s
                ON CONFLICT ON CONSTRAINT uq_rep_traffic_summary_type_window DO UPDATE SET
                    window_end = EXCLUDED.window_end,
                    vehicle_count = EXCLUDED.vehicle_count,
                    avg_speed_kmh = EXCLUDED.avg_speed_kmh;
            """, type_values)
            
            LOG.info(f"Inserted {len(type_values)} records to rep_traffic_summary_5min_by_type")

        conn.commit()
        LOG.info(f"Berhasil memuat data ke PostgreSQL!")
        LOG.info(f"Total windows: {len(total_summary)}")
        LOG.info(f"Unique vehicles: {unique_vehicles}")
        LOG.info(f"Messages processed: {messages_count}")

    except Exception as e:
        conn.rollback()
        LOG.error(f"Error loading to PostgreSQL: {e}")
        raise

    finally:
        cursor.close()
        conn.close()
    
    return "Success"


def validate_data(**context):
    ti = context['ti']
    total_summary = ti.xcom_pull(key='total_summary', task_ids='transform_data')
    
    if not total_summary:
        return "No data to validate"
    
    pg_hook = PostgresHook(postgres_conn_id='postgres_default')
    conn = pg_hook.get_conn()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT window_start, source_id, COUNT(*) as dup_count
            FROM rep_traffic_summary_5min
            WHERE window_start >= NOW() - INTERVAL '1 hour'
            GROUP BY window_start, source_id
            HAVING COUNT(*) > 1;
        """)
        duplicates = cursor.fetchall()
        
        if duplicates:
            LOG.warning(f"Ditemukan duplikasi data: {len(duplicates)}")
            for dup in duplicates:
                LOG.warning(f"{dup[1]} - {dup[0]}: {dup[2]} duplikat")
        else:
            LOG.info("Tidak ada duplikasi data")
        
        cursor.execute("""
            SELECT source_id, AVG(avg_speed_kmh) as avg_speed, 
                   MIN(avg_speed_kmh) as min_speed, 
                   MAX(avg_speed_kmh) as max_speed
            FROM rep_traffic_summary_5min
            WHERE window_start >= NOW() - INTERVAL '1 hour'
            GROUP BY source_id;
        """)
        stats = cursor.fetchall()
        
        for stat in stats:
            LOG.info(f"{stat[0]}: avg={stat[1]:.2f}, min={stat[2]:.2f}, max={stat[3]:.2f} km/h")
            
            if stat[2] < 0 or stat[3] > 200:
                LOG.warning(f"Anomali speed terdeteksi di {stat[0]}! Min={stat[2]}, Max={stat[3]}")
        
    except Exception as e:
        LOG.error(f"Error validasi: {e}")
    finally:
        cursor.close()
        conn.close()
    
    return "Validation completed"


default_args = {
    'owner': 'mahasiswa',
    'start_date': datetime(2026, 1, 1),
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
    'email_on_failure': False,
    'email_on_retry': False,
}

dag = DAG(
    'kafka_to_postgres_summary_dag',
    default_args=default_args,
    description='Agregasi traffic data per 1 jam dari Kafka ke PostgreSQL',
    schedule_interval='0 * * * *',
    catchup=False,
    max_active_runs=1,
    tags=['kafka', 'postgres', 'summary', 'wib'],
)

task1 = PythonOperator(
    task_id='consume_kafka',
    python_callable=consume_from_kafka,
    provide_context=True,
    dag=dag
)

task2 = PythonOperator(
    task_id='transform_data',
    python_callable=transform_and_aggregate,
    provide_context=True,
    dag=dag
)

task3 = PythonOperator(
    task_id='load_summary',
    python_callable=load_summary_to_postgres,
    provide_context=True,
    dag=dag
)

task4 = PythonOperator(
    task_id='validate_data',
    python_callable=validate_data,
    provide_context=True,
    dag=dag
)

task1 >> task2 >> task3 >> task4