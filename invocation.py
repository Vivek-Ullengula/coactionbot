import boto3
import json

client = boto3.client('bedrock-agentcore', region_name='us-east-1')
payload = json.dumps({"prompt": "tell me about class code 10042"})

response = client.invoke_agent_runtime(
    agentRuntimeArn='arn:aws:bedrock-agentcore:us-east-1:975050043926:runtime/underwriting_agent-dXy3Uj6m45',
    runtimeSessionId='<Enter your SessionId>', # Must be 33+ char. Every new SessionId will create a new MicroVM
    payload=payload,
    qualifier="default" # This is Optional. When the field is not provided, Runtime will use DEFAULT endpoint
)
response_body = response['response'].read()
response_data = json.loads(response_body)
print("Agent Response:", response_data)