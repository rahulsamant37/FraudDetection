"""
Real-time Fraud Detection Inference Pipeline

This script consumes transaction data from Kafka, processes it using Spark Streaming,
applies a pre-trained machine learning model to detect fraudulent transactions,
and writes predictions back to Kafka.
"""

# Standard library imports
import logging
import os

# Third-party imports
import joblib  # For loading serialized ML models
import yaml  # For parsing YAML configuration files
from dotenv import load_dotenv  # For loading environment variables from .env file

# PySpark imports
from pyspark.sql import SparkSession
from pyspark.sql.functions import (from_json, col, hour, dayofmonth,
                                  dayofweek, when, lit, coalesce)
from pyspark.sql.pandas.functions import pandas_udf  # For Pandas vectorized UDFs
from pyspark.sql.types import (StructType, StructField, StringType,
                              IntegerType, DoubleType, TimestampType)

# Configure logging to track pipeline operations and errors
logging.basicConfig(
    level=logging.INFO,  # Set logging level to INFO for operational messages
    format="%(asctime)s [%(levelname)s] %(message)s"  # Structured log format
)
logger = logging.getLogger(__name__)  # Create logger instance for the module


class FraudDetectionInference:
    """
    Fraud detection inference pipeline class that handles:
    - Configuration loading
    - Spark session management
    - Kafka stream processing
    - Feature engineering
    - Model inference
    - Results publishing

    Attributes:
        config (dict): Pipeline configuration parameters
        spark (SparkSession): Spark session instance
        model: Loaded ML model for fraud detection
        broadcast_model: Model broadcast to Spark workers for distributed inference
    """

    # Class variables for Kafka configuration
    bootstrap_servers = None
    topic = None
    security_protocol = None
    sasl_mechanism = None
    username = None
    password = None
    sasl_jaas_config = None

    def __init__(self, config_path="/app/config.yaml"):
        """Initialize pipeline with configuration and dependencies

        Args:
            config_path (str): Path to YAML configuration file
        """
        # Load environment variables from .env file
        load_dotenv(dotenv_path="/app/.env")

        # Load pipeline configuration from YAML file
        self.config = self._load_config(config_path)

        # Initialize Spark session with Kafka integration packages
        self.spark = self._init_spark_session()

        # Load and broadcast ML model to worker nodes for distributed inference
        self.model = self._load_model(self.config["model"]["path"])
        self.broadcast_model = self.spark.sparkContext.broadcast(self.model)

        # Debug: Log loaded environment variables (sensitive values should be masked in production)
        logger.debug("Environment variables loaded: %s", dict(os.environ))

    def _load_model(self, model_path):
        """Load pre-trained fraud detection model from disk

        Args:
            model_path (str): Path to serialized model file

        Returns:
            model: Loaded ML model

        Raises:
            Exception: If model loading fails
        """
        try:
            model = joblib.load(model_path)
            logger.info("Model loaded from %s", model_path)
            return model
        except Exception as e:
            logger.error("Error loading model: %s", str(e))
            raise

    @staticmethod
    def _load_config(config_path):
        """Load YAML configuration file

        Args:
            config_path (str): Path to configuration file

        Returns:
            dict: Parsed configuration parameters

        Raises:
            Exception: If file loading or parsing fails
        """
        try:
            with open(config_path, "r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Error loading config: {str(e)}")
            raise

    def _init_spark_session(self):
        """Initialize Spark session with Kafka dependencies

        Returns:
            SparkSession: Configured Spark session

        Raises:
            Exception: If Spark initialization fails
        """
        try:
            # Get required packages from config (typically Kafka integration packages)
            packages = self.config.get("spark", {}).get("packages", "")

            # Build Spark session with application name and packages
            builder = SparkSession.builder.appName("FraudDetectionInferenceStreaming")

            # Add Maven packages if specified in config
            if packages:
                builder = builder.config("spark.jars.packages", packages)

            spark = builder.getOrCreate()
            logger.info("Spark Session initialized.")
            return spark
        except Exception as e:
            logger.error("Error initializing Spark Session: %s", str(e))
            raise

    def read_from_kafka(self):
        """Read streaming data from Kafka topic and parse JSON payload

        Returns:
            DataFrame: Spark DataFrame containing parsed transaction data
        """
        logger.info("Reading data from Kafka topic %s", self.config["kafka"]["topic"])

        # Load Kafka configuration parameters with fallback values
        kafka_config = self.config["kafka"]
        kafka_bootstrap_servers = kafka_config.get("bootstrap_servers", "localhost:9092")
        kafka_topic = kafka_config["topic"]
        kafka_security_protocol = kafka_config.get("security_protocol", "SASL_SSL")
        kafka_sasl_mechanism = kafka_config.get("sasl_mechanism", "PLAIN")
        kafka_username = kafka_config.get("username")
        kafka_password = kafka_config.get("password")

        # Configure Kafka SASL authentication string
        kafka_sasl_jaas_config = (
            f'org.apache.kafka.common.security.plain.PlainLoginModule required '
            f'username="{kafka_username}" password="{kafka_password}";'
        )

        # Store Kafka configuration in instance variables for reuse
        self.bootstrap_servers = kafka_bootstrap_servers
        self.topic = kafka_topic
        self.security_protocol = kafka_security_protocol
        self.sasl_mechanism = kafka_sasl_mechanism
        self.username = kafka_username
        self.password = kafka_password
        self.sasl_jaas_config = kafka_sasl_jaas_config

        # Define schema for incoming JSON transaction data
        json_schema = StructType([
            StructField("transaction_id", StringType(), True),
            StructField("user_id", IntegerType(), True),
            StructField("amount", DoubleType(), True),
            StructField("currency", StringType(), True),
            StructField("merchant", StringType(), True),
            StructField("timestamp", TimestampType(), True),
            StructField("location", StringType(), True),
        ])

        # Create streaming DataFrame from Kafka source
        df = self.spark.readStream \
            .format("kafka") \
            .option("kafka.bootstrap.servers", kafka_bootstrap_servers) \
            .option("subscribe", kafka_topic) \
            .option("startingOffsets", "latest") \
            .option("kafka.security.protocol", kafka_security_protocol) \
            .option("kafka.sasl.mechanism", kafka_sasl_mechanism) \
            .option("kafka.sasl.jaas.config", kafka_sasl_jaas_config) \
            .load()

        # Parse JSON payload using defined schema
        parsed_df = df.selectExpr("CAST(value AS STRING)") \
            .select(from_json(col("value"), json_schema).alias("data")) \
            .select("data.*")

        return parsed_df

    def add_features(self, df):
        """Add engineered features for model inference

        Args:
            df (DataFrame): Input DataFrame with raw transaction data

        Returns:
            DataFrame: DataFrame with additional feature columns
        """
        # Temporal features from transaction timestamp
        df = df.withColumn("transaction_hour", hour(col("timestamp")))
        df = df.withColumn("is_night",
                           when((col("transaction_hour") >= 22) | (col("transaction_hour") < 5), 1).otherwise(0))
        df = df.withColumn("is_weekend",
                           when((dayofweek(col("timestamp")) == 1) | (dayofweek(col("timestamp")) == 7),
                                1).otherwise(0))
        df = df.withColumn("transaction_day", dayofmonth(col("timestamp")))

        # Transaction pattern features (placeholders - would normally come from historical data)
        # In production, these would be calculated using window functions or join with historical data
        df = df.withColumn("time_since_last_txn", lit(0.0))  # Placeholder value
        df = df.withColumn("user_activity_24h", lit(1000))  # Placeholder value
        df = df.withColumn("rolling_avg_7d", lit(1000.0))  # Placeholder value

        # Ratio features to capture transaction amount patterns
        df = df.withColumn("amount_to_avg_ratio", col("amount") / col("rolling_avg_7d"))
        df = df.withColumn("amount_to_avg_ratio", coalesce(col("amount_to_avg_ratio"), lit(1.0)))

        # Merchant risk features from configurable list of high-risk merchants
        high_risk_merchants = self.config.get('high_risk_merchants', ['QuickCash', 'GlobalDigital', 'FastMoneyX'])
        df = df.withColumn("merchant_risk", col("merchant").isin(high_risk_merchants).cast("int"))

        # Debug: Output schema of processed data for verification
        df.printSchema()
        return df

    def run_inference(self):
        """Main pipeline execution flow: process stream and run predictions"""
        # Local import for Spark executor compatibility
        import pandas as pd

        # Process streaming data from Kafka
        df = self.read_from_kafka()

        # Define watermark to handle late-arriving data (24 hour tolerance)
        df = df.withWatermark("timestamp", "24 hours")

        # Add engineered features to raw data
        feature_df = self.add_features(df)

        # Get broadcasted model reference for use in UDF
        broadcast_model = self.broadcast_model

        # Define prediction UDF using Pandas for vectorized operations
        @pandas_udf("int")
        def predict_udf(
                user_id: pd.Series,
                amount: pd.Series,
                currency: pd.Series,
                transaction_hour: pd.Series,
                is_weekend: pd.Series,
                time_since_last_txn: pd.Series,
                merchant_risk: pd.Series,
                amount_to_avg_ratio: pd.Series,
                is_night: pd.Series,
                transaction_day: pd.Series,
                user_activity_24h: pd.Series,
                merchant: pd.Series
        ) -> pd.Series:
            """Vectorized UDF for batch prediction using pre-trained model

            Args:
                Various Pandas Series containing feature values

            Returns:
                pd.Series: Binary predictions (0=legitimate, 1=fraud)
            """
            # Create input DataFrame from feature columns
            input_df = pd.DataFrame({
                "user_id": user_id,
                "amount": amount,
                "currency": currency,
                "transaction_hour": transaction_hour,
                "is_weekend": is_weekend,
                "time_since_last_txn": time_since_last_txn,
                "merchant_risk": merchant_risk,
                "amount_to_avg_ratio": amount_to_avg_ratio,
                "is_night": is_night,
                "transaction_day": transaction_day,
                "user_activity_24h": user_activity_24h,
                "merchant": merchant
            })

            # Get fraud probabilities and apply classification threshold
            probabilities = broadcast_model.value.predict_proba(input_df)[:, 1]
            threshold = 0.60  # Tuned based on precision/recall requirements
            predictions = (probabilities >= threshold).astype(int)
            return pd.Series(predictions)

        # Apply predictions to streaming DataFrame
        prediction_df = feature_df.withColumn("prediction", predict_udf(
            *[col(f) for f in [
                "user_id", "amount", "currency", "transaction_hour",
                "is_weekend", "time_since_last_txn", "merchant_risk",
                "amount_to_avg_ratio", "is_night", "transaction_day",
                "user_activity_24h", "merchant"
            ]]
        ))

        # Filter to only include high-confidence fraud predictions
        fraud_predictions = prediction_df.filter(col("prediction") == 1)

        # Write results back to Kafka topic
        (fraud_predictions.selectExpr(
            "CAST(transaction_id AS STRING) AS key",
            "to_json(struct(*)) AS value"  # Serialize all fields as JSON
        )
         .writeStream
         .format("kafka")
         .option("kafka.bootstrap.servers", self.bootstrap_servers)
         .option("topic", 'fraud_predictions')  # Output topic for fraud alerts
         .option("kafka.security.protocol", self.security_protocol)
         .option("kafka.sasl.mechanism", self.sasl_mechanism)
         .option("kafka.sasl.jaas.config", self.sasl_jaas_config)
         .option("checkpointLocation", "checkpoints/checkpoint")  # For fault tolerance and recovery
         .outputMode("update")  # Only write updated records
         .start()
         .awaitTermination())  # Keep the streaming context alive


if __name__ == "__main__":
    """Main entry point for the inference pipeline"""
    # Initialize pipeline with configuration
    inference = FraudDetectionInference("/app/config.yaml")

    # Start streaming processing and block until termination
    inference.run_inference()