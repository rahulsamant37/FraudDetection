from datetime import datetime, timedelta

from airflow import DAG
from airflow.exceptions import AirflowException
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
import logging

logger = logging.getLogger(__name__)

default_args = {
    'owner': 'datamasterylab.com',
    'depends_on_past': False,
    'start_date': datetime(2025, 3, 3),
    # 'execution_timeout': timedelta(minutes=120),
    'max_active_runs': 1,
}

def _train_model(**context):
    """Airflow wrapper for training task"""
    from fraud_detection_training import FraudDetectionTraining
    try:
        logger.info('Initializing fraud detection training')
        trainer = FraudDetectionTraining()
        model, precision = trainer.train_model()

        return { 'status': 'success', 'precision': precision }
    except Exception as e:
        logger.error('Training failed: %s', str(e), exc_info=True)
        raise AirflowException(f'Model training failed: {str(e)}')

with DAG(
    'fraud_detection_training',
    default_args=default_args,
    description='Fraud detection model training pipeline',
    schedule_interval='0 3 * * *',
    catchup=False,
    tags=['fraud', 'ML']
) as dag:
    validate_environment = BashOperator(
        task_id='validate_environment',
        bash_command='''
        echo "Validating environment..."
        test -f /app/config.yaml &&
        test -f /app/.env && 
        echo "Environment is valid!"
        '''
    )

    training_task  = PythonOperator(
        task_id='execute_training',
        python_callable=_train_model,
        provide_context=True,
    )

    cleanup_task = BashOperator(
        task_id='cleanup_resources',
        bash_command='rm -f /app/tmp/*.pkl',
        trigger_rule='all_done'
    )

    validate_environment >> training_task >> cleanup_task

    # Documentation
    dag.doc_md = """
    ## Fraud Detection Training Pipeline
    
    Daily training of fraud detection model using:
    - Transaction data from Kafka
    - XGBoost classifier with precision optimisation
    - MLFlow for experiment tracking
    """