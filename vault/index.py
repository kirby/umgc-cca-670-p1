import botocore
import boto3
import json
import logging
import os

from crhelper import CfnResource
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

helper = CfnResource(
  json_logging=True,
  log_level='DEBUG',
  boto_level='CRITICAL',
  sleep_on_delete=60,
)

try:

  glacier_client = boto3.client('glacier')
  sns_client = boto3.client('sns')

except Exception as e:
  helper.init_failure(e)

def handler(event, context):
  helper(event, context)

@helper.create
def create_handler(event, context):
  """
  Called when CloudFormation custom resource sends the create event
  """
  account_id = get_account_id(event)
  region = get_region(event)
  vault_name = get_vault_name(event)
  vault_bytes_per_hour  = get_vault_bytes_per_hour(event)
  vault_archive_age_in_days = get_vault_archive_age_in_days(event)

  sns_topic = create_sns_topic(vault_name)

  if sns_topic:

    if create_vault(vault_name, sns_topic):

      if initiate_and_complete_vault_lock_policy(
        vault_name,
        get_vault_access_policy(region, account_id, vault_name, vault_archive_age_in_days)):

          if set_data_retrieval_policy(vault_bytes_per_hour):

            return True

  return False

@helper.delete
def delete_handler(event, context):
  """
  Called when CloudFormation custom resource sends the delete event
  """

  region = get_region(event)
  account_id = get_account_id(event)
  vault_name = get_vault_name(event)

  r = glacier_client.delete_vault_notifications(
    vaultName=vault_name
  )

  r = delete_sns_topic(region, account_id, vault_name)

  response = delete_vault(vault_name)

  logger.info(f'r = {r}')

  return response

@helper.update
def noop():
    """
    Not currently implemented but crhelper will throw an error if it isn't added
    """
    pass

# Helper Functions

def get_account_id(event):
  return event['ResourceProperties']['AccountId']

def get_region(event):
  return event['ResourceProperties']['Region']

def get_vault_name(event):
  return event['ResourceProperties']['VaultName']

def get_vault_bytes_per_hour(event):
  return event['ResourceProperties']['VaultBytesPerHour']

def get_vault_archive_age_in_days(event):
  return event['ResourceProperties']['VaultArchiveAgeInDays']


# https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glacier.html#Glacier.Client.set_data_retrieval_policy
def get_data_retrieval_policy(vault_bytes_per_hour):

  policy = {
    'Rules': [
        {
            'Strategy': 'BytesPerHour',
            'BytesPerHour': vault_bytes_per_hour
        },
    ]
  }

  return policy

# https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glacier.html#Glacier.Client.set_vault_access_policy
def get_vault_access_policy(region, account_id, vault_name, vault_archive_age_in_days):

  policy = {
    'Version': '2012-10-17',
    'Statement': [
      {
        'Principal': '*',
        'Effect': 'Deny',
        'Action': [
          'glacier:DeleteArchive'
        ],
        'Resource': [
          f'arn:aws:glacier:{region}:{account_id}:vaults/{vault_name}'
        ],
        'Condition': {
          'StringLike': {
            'glacier:ResourceTag/LegalHold': [
              'true',
              ''
            ]
          }
        }
      },
      {
        'Principal': {
          f'AWS': f'arn:aws:iam::{account_id}:root'
        },
        'Effect': 'Allow',
        'Action': [
          'glacier:DeleteArchive'
        ],
        'Resource': [
          f'arn:aws:glacier:{region}:{account_id}:vaults/{vault_name}'
        ],
        'Condition': {
          'NumericLessThan': {
            'glacier:ArchiveAgeInDays': f'{vault_archive_age_in_days}'
          }
        }
      }
    ]
  }

  return policy

def create_sns_topic(vault_name):

  response = None

  try:

    r = sns_client.create_topic(
      Name=vault_name
    )

    helper.Data['TopicArn'] = r['TopicArn']

    response = r['TopicArn']

  except botocore.exceptions.ClientError as err:

    # raise err
    logger.error(err)
    response = False

    # SNS.Client.exceptions.InvalidParameterException
    # SNS.Client.exceptions.TopicLimitExceededException
    # SNS.Client.exceptions.InternalErrorException
    # SNS.Client.exceptions.AuthorizationErrorException
    # SNS.Client.exceptions.InvalidSecurityException
    # SNS.Client.exceptions.TagLimitExceededException
    # SNS.Client.exceptions.StaleTagException
    # SNS.Client.exceptions.TagPolicyException
    # SNS.Client.exceptions.ConcurrentAccessException

  return response


def delete_sns_topic(region, accountId, vault_name):

  response = None

  try:

    response = sns_client.delete_topic(
      TopicArn=f'arn:aws:sns:{region}:{accountId}:{vault_name}'
    )

  except botocore.exceptions.ClientError as err:

    # raise err
    logger.error(err)
    response = False

    # SNS.Client.exceptions.InvalidParameterException
    # SNS.Client.exceptions.InternalErrorException
    # SNS.Client.exceptions.AuthorizationErrorException
    # SNS.Client.exceptions.NotFoundException
    # SNS.Client.exceptions.StaleTagException
    # SNS.Client.exceptions.TagPolicyException
    # SNS.Client.exceptions.ConcurrentAccessException

  return response


def create_vault(vault_name, sns_topic):
  response = False

  try:

    r = glacier_client.create_vault(
      accountId='-',
      vaultName=vault_name
    )

    if r['ResponseMetadata']['HTTPStatusCode'] == 201:

      helper.Data['VaultLocation'] = r['location']    

      r = glacier_client.add_tags_to_vault(
        vaultName=vault_name,
        Tags={
            'CreatedBy': 'Ballot Online DevOps'
        }
      )     

      r = glacier_client.set_vault_notifications(
        accountId='-',
        vaultName=vault_name,
        vaultNotificationConfig={
          'SNSTopic': sns_topic,
          'Events': [
            'ArchiveRetrievalCompleted',
            'InventoryRetrievalCompleted',
          ]
        }
      )

      response = True
    else:
      response = False

  except botocore.exceptions.ClientError as err:

    # raise err
    logger.error(err)
    response = False

    # Glacier.Client.exceptions.InvalidParameterValueException
    # Glacier.Client.exceptions.MissingParameterValueException
    # Glacier.Client.exceptions.ServiceUnavailableException
    # Glacier.Client.exceptions.LimitExceededException

    # Glacier.Client.exceptions.InvalidParameterValueException
    # Glacier.Client.exceptions.MissingParameterValueException
    # Glacier.Client.exceptions.ResourceNotFoundException
    # Glacier.Client.exceptions.LimitExceededException
    # Glacier.Client.exceptions.ServiceUnavailableException     

    # Glacier.Client.exceptions.ResourceNotFoundException
    # Glacier.Client.exceptions.InvalidParameterValueException
    # Glacier.Client.exceptions.MissingParameterValueException
    # Glacier.Client.exceptions.ServiceUnavailableException    

  return response


def delete_vault(vault_name):

  response = False

  try:

    r = glacier_client.delete_vault(
      accountId='-',
      vaultName=vault_name
    )

    logger.info(f'vault_delete = {r}')

    if r['ResponseMetadata']['HTTPStatusCode'] == 201:
      response = True
    else:
      response = False

  except botocore.exceptions.ClientError as err:

    # raise err
    logger.error(err)
    response = False

    # Glacier.Client.exceptions.ResourceNotFoundException
    # Glacier.Client.exceptions.InvalidParameterValueException
    # Glacier.Client.exceptions.MissingParameterValueException
    # Glacier.Client.exceptions.ServiceUnavailableException

  return response


def set_data_retrieval_policy(policy):

  logger.info(f'policy = {policy}')

  response = False

  try:

    r = glacier_client.set_data_retrieval_policy(
      accountId='-',
      Policy={
        'Rules': [
            {
                'Strategy': 'BytesPerHour',
                'BytesPerHour': int(policy)
            },
        ]
    }
    )

    logger.info(f'set_data_retrieval_policy = {r}')

    response = True

  except botocore.exceptions.ClientError as err:

    # raise err
    logger.error(err)
    response = False

    # Glacier.Client.exceptions.InvalidParameterValueException
    # Glacier.Client.exceptions.MissingParameterValueException
    # Glacier.Client.exceptions.ServiceUnavailableException


  return response


# https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glacier.html#Glacier.Client.initiate_vault_lock
def initiate_and_complete_vault_lock_policy(vault_name, policy):

  response = False

  policy = json.dumps(policy, ensure_ascii=True, indent=None)

  # logger.info(f'type(policy) = {type(policy)}')
  # logger.info(policy)

  try:

    r = glacier_client.initiate_vault_lock(
      accountId='-',
      vaultName=vault_name,
      policy={
        'Policy': f'{policy}'
      }
    )

    logger.info(f'initiate_vault_lock = {r}')

    lock_id = r['lockId']

    r = glacier_client.complete_vault_lock(
        accountId='-',
        lockId=lock_id,
        vaultName=vault_name
    )    

    logger.info(f'complete_vault_lock = {r}')

    return True

  except botocore.exceptions.ClientError as err:

    # raise err
    logger.error(err)
    response = False

    # Glacier.Client.exceptions.ResourceNotFoundException
    # Glacier.Client.exceptions.InvalidParameterValueException
    # Glacier.Client.exceptions.MissingParameterValueException
    # Glacier.Client.exceptions.ServiceUnavailableException

  return response

