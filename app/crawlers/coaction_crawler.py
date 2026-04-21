import asyncio
import json
import re
import os
from urllib.parse import urlparse
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from app.logger import get_logger

logger = get_logger(__name__)

class CoactionCrawler:
    """
    Specialized crawler for Coaction manual content using Crawl4AI.
    Implements domain-specific chunking for Class Codes and Guide pages.
    """

    def __init__(self, start_url: str):
        self.start_url = start_url
        self.base_domain = urlparse(start_url).netloc
        self.base_path = "/manuals/"
        self.visited = set()
        self.page_contents = {}

    def is_valid_url(self, url: str) -> bool:
        parsed = urlparse(url)
        clean = parsed._replace(fragment="").geturl()
        return (
            parsed.netloc == self.base_domain and
            parsed.path.startswith(self.base_path) and
            clean not in self.visited
        )

    def normalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed._replace(fragment="").geturl()

    def extract_links(self, markdown: str, base_url: str) -> list[str]:
        pattern = r'\[.*?\]\((http[s]?://[^\)]+)\)'
        links = re.findall(pattern, markdown)
        valid = []
        for l in links:
            norm = self.normalize_url(l)
            if self.is_valid_url(norm):
                valid.append(norm)
        return valid

    def clean_text(self, text: str) -> str:
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text, flags=re.DOTALL)
        text = re.sub(r'!\[([^\]]*)\]', '', text)
        text = re.sub(r'AI-generated content may be incorrect\.', '', text)
        text = re.sub(r'\[([^\]]+)\]\(https://bindingauthority[^\)]+#[^\)]+\)', r'\1', text)
        text = re.sub(r'https?://\S+', '', text)
        text = re.sub(r'#{1,3}\s*\n', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def is_class_code_page(self, url: str) -> bool:
        return bool(re.search(r'/manuals/\d+\.html$', url))

    def extract_class_code(self, url: str) -> str:
        m = re.search(r'/manuals/(\d+)\.html', url)
        return m.group(1) if m else None

    def extract_class_name(self, text: str, code: str) -> str:
        m = re.search(rf'{code}\s*[–\-]\s*([^\n*\[]+)', text)
        return m.group(1).strip() if m else ""

    def chunk_class_code_page(self, text: str, url: str, code: str) -> list[dict]:
        class_name = self.extract_class_name(text, code)
        prefix = f"Class Code: {code}"
        if class_name:
            prefix += f" — {class_name}"

        full_text = f"{prefix}\n\n{text}"

        if len(full_text) <= 8000:
            return [{
                "text": full_text,
                "metadata": {
                    "source_url": url,
                    "heading": prefix,
                    "class_code": code,
                    "class_name": class_name,
                    "chunk_type": "class_code_full"
                }
            }]
        else:
            sections = re.split(r'\n(?=# )', text)
            chunks = []
            for section in sections:
                section = section.strip()
                if len(section.split()) < 15:
                    continue
                section_heading = re.match(r'# (.+)', section.split('\n')[0])
                heading_text = section_heading.group(1).strip() if section_heading else prefix
                chunks.append({
                    "text": f"{prefix}\n{heading_text}\n\n{section}",
                    "metadata": {
                        "source_url": url,
                        "heading": f"{prefix} — {heading_text}",
                        "class_code": code,
                        "class_name": class_name,
                        "chunk_type": "class_code_section"
                    }
                })
            return chunks if chunks else [{
                "text": full_text[:8000],
                "metadata": {
                    "source_url": url,
                    "heading": prefix,
                    "class_code": code,
                    "class_name": class_name,
                    "chunk_type": "class_code_full"
                }
            }]

    def chunk_guide_page(self, text: str, url: str) -> list[dict]:
        sections = re.split(r'\n(?=#{1,3} )', text)
        chunks = []

        for section in sections:
            section = section.strip()
            if len(section.split()) < 20:
                continue

            heading_match = re.match(r'#{1,3} (.+)', section.split('\n')[0])
            heading = heading_match.group(1).strip() if heading_match else "General"
            heading = re.sub(r'[_*]', '', heading).strip()

            if len(section) <= 6000:
                chunks.append({
                    "text": section,
                    "metadata": {
                        "source_url": url,
                        "heading": heading,
                        "chunk_type": "guide_section"
                    }
                })
            else:
                paragraphs = section.split('\n\n')
                current = ""
                for para in paragraphs:
                    if len(current) + len(para) <= 6000:
                        current += "\n\n" + para
                    else:
                        if current.strip() and len(current.split()) >= 20:
                            chunks.append({
                                "text": current.strip(),
                                "metadata": {
                                    "source_url": url,
                                    "heading": heading,
                                    "chunk_type": "guide_section"
                                }
                            })
                        current = para
                if current.strip() and len(current.split()) >= 20:
                    chunks.append({
                        "text": current.strip(),
                        "metadata": {
                            "source_url": url,
                            "heading": heading,
                            "chunk_type": "guide_section"
                        }
                    })

        return chunks

    async def _crawl_recursive(self, url: str, crawler: AsyncWebCrawler):
        norm_url = self.normalize_url(url)
        if norm_url in self.visited:
            return
        self.visited.add(norm_url)
        logger.info(f"Crawling: {norm_url}")

        config = CrawlerRunConfig(word_count_threshold=10)
        result = await crawler.arun(url=norm_url, config=config)

        if not result.success:
            logger.warning(f"  Failed to crawl: {norm_url}")
            return

        cleaned = self.clean_text(result.markdown)
        self.page_contents[norm_url] = cleaned

        links = self.extract_links(result.markdown, norm_url)
        tasks = [self._crawl_recursive(link, crawler) for link in links]
        await asyncio.gather(*tasks)

    async def run(self) -> list[dict]:
        """Runs the crawler and returns all generated chunks."""
        async with AsyncWebCrawler() as crawler:
            await self._crawl_recursive(self.start_url, crawler)

        logger.info(f"\nCrawled {len(self.page_contents)} unique pages")

        all_chunks = []
        seen_fingerprints = set()

        for url, text in self.page_contents.items():
            if self.is_class_code_page(url):
                code = self.extract_class_code(url)
                chunks = self.chunk_class_code_page(text, url, code)
            else:
                chunks = self.chunk_guide_page(text, url)

            for chunk in chunks:
                fp = chunk["text"][:150]
                if fp in seen_fingerprints:
                    continue
                seen_fingerprints.add(fp)
                all_chunks.append(chunk)

        # Force trim anything over 8000 chars
        for chunk in all_chunks:
            if len(chunk["text"]) > 8000:
                chunk["text"] = chunk["text"][:8000]

        return all_chunks
