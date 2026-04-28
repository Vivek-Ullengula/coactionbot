import boto3
import re
from strands import tool
from app.core.config import get_settings
from app.core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

_bedrock_client = None

def get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client(
            'bedrock-agent-runtime',
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key
        )
    return _bedrock_client

def expand_query(query: str) -> str:
    search_query = query
    eligibility_keywords = ["acceptable", "eligible", "appetite", "suitability", "cover", "prohibited"]
    if any(k in query.lower() for k in eligibility_keywords):
        search_query = f"{query} class code prohibited submit requirements eligibility"
        logger.info("query_expanded", original=query, expanded=search_query)
    return search_query

def fetch_bedrock_results(search_query: str) -> list:
    client = get_bedrock_client()
    response = client.retrieve(
        knowledgeBaseId=settings.bedrock_kb_id,
        retrievalQuery={'text': search_query},
        retrievalConfiguration={
            'vectorSearchConfiguration': {
                'numberOfResults': 5,
                'overrideSearchType': 'HYBRID'
            }
        }
    )
    return response.get('retrievalResults', [])

def format_retrieved_documents(results: list, original_query: str) -> str:
    specific_codes = re.findall(r'(\d{4,})', original_query)
    
    context_parts = []
    
    for _, res in enumerate(results):
        content = res.get('content', {}).get('text', '')
        metadata = res.get('metadata', {})
        
        if specific_codes:
            found_code = any(code in content.replace(" ", "") for code in specific_codes)
            if not found_code:
                continue

        s3_uri = metadata.get('source_url') or metadata.get('sourceUrl') or ''
        injected_url_match = re.search(r'^SOURCE_URL:\s*(https?://\S+)', content, re.MULTILINE)
        injected_code_match = re.search(r'^CLASS_CODE:\s*(\d+)', content, re.MULTILINE)
        
        if injected_url_match:
            url = injected_url_match.group(1).strip()
        elif 'full-page-crawl/' in s3_uri:
            filename = s3_uri.split('/')[-1].replace('.md', '.html')
            url = f"https://bindingauthority.coactionspecialty.com/manuals/{filename}"
        else:
            url = s3_uri or 'N/A'
        
        if injected_code_match:
            class_code = injected_code_match.group(1)
            heading = f"Class Code {class_code}"
        else:
            header_match = re.search(r'^#+\s*(.+)', content, re.MULTILINE)
            heading = metadata.get('heading') or (header_match.group(1) if header_match else "Manual Section")
        
        clean_content = re.sub(r'^(SOURCE_URL|CLASS_CODE):.*\n?', '', content, flags=re.MULTILINE).strip()
        clean_content = re.sub(r'^---\s*\n', '', clean_content).strip()

        part = f"Source: {url}\nHeading: {heading}\nContent:\n{clean_content}"
        context_parts.append(part)
    
    if not context_parts:
        return "No relevant information found in the manuals."
        
    return "\n\n".join(context_parts)

@tool
def search_manuals(query: str) -> str:
    """Search the Coaction underwriting manuals (General Liability and Property) using the AWS Knowledge Base.

    Args:
        query: The search query to find relevant manual content.
    """
    try:
        search_query = expand_query(query)
        results = fetch_bedrock_results(search_query)
        logger.info("retrieval_complete", result_count=len(results))
        return format_retrieved_documents(results, query)
    except Exception as e:
        logger.error("bedrock_retrieval_failed", error=str(e))
        return f"Error searching manuals: {str(e)}"
