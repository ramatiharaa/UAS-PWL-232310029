from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, DoubleType

JAR_PATH = ",".join([
    "/opt/spark-apps/jars/postgresql-42.7.3.jar",
    "/opt/spark-apps/jars/spark-sql-kafka-0-10_2.12-3.3.0.jar",
    "/opt/spark-apps/jars/kafka-clients-3.3.1.jar",
    "/opt/spark-apps/jars/spark-token-provider-kafka-0-10_2.12-3.3.0.jar",
    "/opt/spark-apps/jars/commons-pool2-2.11.1.jar",
])

JDBC_URL = "jdbc:postgresql://postgree-db:5432/traffic_db"
JDBC_USER = "admin"
JDBC_PASSWORD = "password123"
JDBC_DRIVER = "org.postgresql.Driver"

spark = SparkSession.builder \
    .appName("TrafficETLRealtime") \
    .master("local[*]") \
    .config("spark.jars", JAR_PATH) \
    .config("spark.driver.memory", "2g") \
    .config("spark.sql.shuffle.partitions", "2") \
    .config("spark.sql.session.timeZone", "Asia/Jakarta") \
    .getOrCreate()

spark.sparkContext.setLogLevel("WARN")

schema = StructType([
    StructField("source_id", StringType(), True),
    StructField("tracker_id", IntegerType(), True),
    StructField("vehicle_type", StringType(), True),
    StructField("speed_kmh", DoubleType(), True),
    StructField("confidence", DoubleType(), True),
    StructField("timestamp", StringType(), True),
    StructField("processing_time", StringType(), True),
    StructField("frame", IntegerType(), True),
    StructField("position_meters", StructType([
        StructField("x", DoubleType(), True),
        StructField("y", DoubleType(), True)
    ]), True),
    StructField("trajectory_length", IntegerType(), True)
])

print("Reading from Kafka topic: traffic-data-topic")

df = spark.readStream \
    .format("kafka") \
    .option("kafka.bootstrap.servers", "kafka:29092") \
    .option("subscribe", "traffic-data-topic") \
    .option("startingOffsets", "latest") \
    .option("failOnDataLoss", "false") \
    .option("maxOffsetsPerTrigger", "3000") \
    .load()

parsed_df = df.select(
    F.from_json(
        F.col("value").cast("string"),
        schema
    ).alias("data")
).select("data.*")

filtered_df = parsed_df.filter(
    F.col("source_id").isNotNull() &
    F.col("vehicle_type").isNotNull() &
    F.col("speed_kmh").isNotNull() &
    F.col("tracker_id").isNotNull() &
    (F.col("speed_kmh") >= 0) &
    (F.col("speed_kmh") < 150) &
    (F.col("confidence") > 0.3)
)

print("Converting timestamps...")

parsed_with_time = filtered_df.withColumn(
    "event_time_wib",
    F.to_timestamp(F.col("timestamp"), "yyyy-MM-dd HH:mm:ss")
)

valid_time_df = parsed_with_time.filter(F.col("event_time_wib").isNotNull())

print("Aggregating data per 5 seconds...")

aggregated_df = valid_time_df \
    .withWatermark("event_time_wib", "5 seconds") \
    .groupBy(
        F.col("source_id"),
        F.window(F.col("event_time_wib"), "5 seconds", "5 seconds")
    ) \
    .agg(
        F.approx_count_distinct("tracker_id").alias("total_count"),
        F.avg("speed_kmh").alias("avg_speed"),
        F.max("speed_kmh").alias("max_speed"),
        F.min("speed_kmh").alias("min_speed"),
        F.avg("confidence").alias("avg_confidence")
    )

def determine_traffic_status(avg_speed, total_count):
    if total_count is None or total_count == 0 or avg_speed is None:
        return "SEPI"
    if total_count <= 2:
        return "LANCAR"
    if avg_speed < 10:
        return "MACET"
    if avg_speed < 30:
        return "PADAT"
    return "LANCAR"

from pyspark.sql.types import StringType
traffic_status_udf = F.udf(determine_traffic_status, StringType())

aggregated_df = aggregated_df \
    .withColumn("window_start", F.col("window.start")) \
    .withColumn("window_end", F.col("window.end")) \
    .drop("window")

aggregated_df = aggregated_df.withColumn(
    "traffic_status",
    traffic_status_udf(F.col("avg_speed"), F.col("total_count"))
)

def upsert_to_postgres(batch_df, batch_id):
    if batch_df.isEmpty():
        print(f"[UPSERT] Batch {batch_id} empty, skipping...")
        return
    
    try:
        print(f"[UPSERT] Processing batch {batch_id}...")
        
        from pyspark.sql import functions as F_local
        
        dedup_df = batch_df.groupBy("source_id").agg(
            F_local.max("window_start").alias("window_start"),
            F_local.max("window_end").alias("window_end"),
            F_local.max("total_count").alias("total_count"),
            F_local.max("avg_speed").alias("avg_speed"),
            F_local.max("max_speed").alias("max_speed"),
            F_local.min("min_speed").alias("min_speed"),
            F_local.last("traffic_status").alias("traffic_status")
        )
        
        write_df = dedup_df.select(
            F.col("source_id"),
            F.col("window_start"),
            F.col("window_end"),
            F.col("total_count").cast("int"),
            F.col("avg_speed").cast("decimal(6,2)"),
            F.col("max_speed").cast("decimal(6,2)"),
            F.col("min_speed").cast("decimal(6,2)"),
            F.col("traffic_status"),
            F.current_timestamp().alias("created_at"),
            F.current_timestamp().alias("updated_at")
        )
        
        write_df.write \
            .format("jdbc") \
            .option("url", JDBC_URL) \
            .option("dbtable", "traffic_real_time_aggregated_temp") \
            .option("user", JDBC_USER) \
            .option("password", JDBC_PASSWORD) \
            .option("driver", JDBC_DRIVER) \
            .mode("overwrite") \
            .save()
        
        print(f"   Temp table written: {write_df.count()} records")
        
        from py4j.java_gateway import java_import
        
        spark_session = SparkSession.getActiveSession()
        if spark_session is None:
            spark_session = spark
        
        jvm = spark_session._jvm
        java_import(jvm, "java.sql.DriverManager")
        java_import(jvm, "java.util.Properties")
        
        props = jvm.java.util.Properties()
        props.setProperty("user", JDBC_USER)
        props.setProperty("password", JDBC_PASSWORD)
        
        conn = jvm.java.sql.DriverManager.getConnection(JDBC_URL, props)
        stmt = conn.createStatement()
        
        upsert_query = """
            INSERT INTO traffic_real_time_aggregated 
            (source_id, window_start, window_end, total_count, avg_speed, 
             max_speed, min_speed, traffic_status, created_at, updated_at)
            SELECT 
                source_id, window_start, window_end, total_count, avg_speed,
                max_speed, min_speed, traffic_status, created_at, updated_at
            FROM traffic_real_time_aggregated_temp
            ON CONFLICT (source_id) 
            DO UPDATE SET
                window_start = EXCLUDED.window_start,
                window_end = EXCLUDED.window_end,
                total_count = EXCLUDED.total_count,
                avg_speed = EXCLUDED.avg_speed,
                max_speed = EXCLUDED.max_speed,
                min_speed = EXCLUDED.min_speed,
                traffic_status = EXCLUDED.traffic_status,
                updated_at = EXCLUDED.updated_at;
            
            DROP TABLE traffic_real_time_aggregated_temp;
        """
        
        stmt.execute(upsert_query)
        stmt.close()
        conn.close()
        
        print(f"Batch {batch_id}: UPSERT {write_df.count()} records")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

print("=" * 60)
print("Starting streaming queries...")
print("=" * 60)

query_aggregated = aggregated_df.writeStream \
    .outputMode("update") \
    .foreachBatch(upsert_to_postgres) \
    .trigger(processingTime="30 seconds") \
    .option("checkpointLocation", "/tmp/checkpoint/traffic_aggregated") \
    .start()

print(" Streaming started! UPSERT to PostgreSQL every 30 seconds")
print("   Each source_id (camera) will have only 1 record (updated)")
print("=" * 60)
print("Waiting for termination...")

spark.streams.awaitAnyTermination()