#!/usr/bin/env python3
"""
Simple script to scrape a website and upload to S3.
Usage: python scrape.py https://your-site.com
"""
import asyncio
import sys
from app.utils.add_index import index_url_to_bedrock_kb


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scrape.py <url>")
        print("Example: python scrape.py https://docs.example.com")
        sys.exit(1)
    
    url = sys.argv[1]
    max_depth = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    max_pages = int(sys.argv[3]) if len(sys.argv) > 3 else 50
    
    print(f"Scraping: {url}")
    print(f"Max depth: {max_depth}")
    print(f"Max pages: {max_pages}")
    print()
    
    result = await index_url_to_bedrock_kb(
        url=url,
        max_depth=max_depth,
        max_pages=max_pages
    )
    
    print()
    print("="*60)
    print("✓ DONE")
    print("="*60)
    print(f"Pages crawled: {result['pages_crawled']}")
    print(f"Documents uploaded: {result['documents_uploaded']}")
    if result.get('upload_failures', 0) > 0:
        print(f"Upload failures: {result['upload_failures']}")
    print()
    print("Next steps:")
    print("1. Verify documents in S3:")
    print("   aws s3 ls s3://your-bucket/web/ --recursive")
    print()
    print("2. Start ingestion job:")
    print("   Go to AWS Bedrock Console -> Knowledge Bases -> Your KB -> Sync/Ingest")


if __name__ == '__main__':
    asyncio.run(main())
