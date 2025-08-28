# backend/app/services/zip_service.py
import os
import zipfile
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple
from datetime import datetime

from ..config import settings
from ..models import ProcessingResult


class ZipService:
    """Service for creating ZIP archives of processed documents."""
    
    def __init__(self):
        self.processed_dir = Path(settings.processed_dir)
    
    def create_zip_archive(
        self, 
        document_ids: List[str], 
        zip_name: Optional[str] = None,
        include_summary: bool = True
    ) -> Tuple[str, int]:
        """
        Create a ZIP archive containing processed documents.
        
        Args:
            document_ids: List of document IDs to include
            zip_name: Optional custom name for the ZIP file
            include_summary: Whether to include a processing summary file
            
        Returns:
            Tuple of (zip_file_path, file_count)
        """
        if not zip_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_name = f"curatore_export_{timestamp}.zip"
        elif not zip_name.endswith('.zip'):
            zip_name += '.zip'
        
        # Create temporary ZIP file
        temp_dir = tempfile.gettempdir()
        zip_path = os.path.join(temp_dir, zip_name)
        
        file_count = 0
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add processed documents
            for doc_id in document_ids:
                # Find the processed markdown file for this document
                for file_path in self.processed_dir.glob(f"*_{doc_id}.md"):
                    if file_path.exists():
                        # Use original filename without the ID prefix
                        original_name = file_path.name.split('_', 1)[-1] if '_' in file_path.name else file_path.name
                        zipf.write(file_path, f"processed_documents/{original_name}")
                        file_count += 1
                        break
            
            # Add summary file if requested
            if include_summary and file_count > 0:
                summary_content = self._generate_zip_summary(document_ids, file_count)
                summary_filename = f"PROCESSING_SUMMARY_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                zipf.writestr(summary_filename, summary_content)
        
        return zip_path, file_count
    
    def create_combined_markdown_zip(
        self,
        document_ids: List[str],
        results: List[ProcessingResult],
        zip_name: Optional[str] = None
    ) -> Tuple[str, int]:
        """
        Create a ZIP archive containing both individual files and a combined markdown file.
        
        Args:
            document_ids: List of document IDs to include
            results: List of processing results for metadata
            zip_name: Optional custom name for the ZIP file
            
        Returns:
            Tuple of (zip_file_path, file_count)
        """
        if not zip_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_name = f"curatore_combined_export_{timestamp}.zip"
        elif not zip_name.endswith('.zip'):
            zip_name += '.zip'
        
        # Create temporary ZIP file
        temp_dir = tempfile.gettempdir()
        zip_path = os.path.join(temp_dir, zip_name)
        
        file_count = 0
        combined_sections = []
        
        # Generate combined markdown header
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        successful_results = [r for r in results if r.success]
        rag_ready_results = [r for r in successful_results if r.pass_all_thresholds]
        vector_optimized_results = [r for r in successful_results if r.vector_optimized]
        pass_rate = (len(rag_ready_results) / len(successful_results) * 100) if successful_results else 0
        
        combined_sections.extend([
            "# Curatore Processing Results - Combined Export",
            f"*Generated on {timestamp}*",
            "",
            "**Processing Summary:**",
            f"- Total Files: {len(successful_results)}",
            f"- RAG Ready: {len(rag_ready_results)} ({pass_rate:.1f}%)",
            f"- Vector Optimized: {len(vector_optimized_results)}",
            "",
            "---",
            ""
        ])
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add individual processed documents
            for doc_id in document_ids:
                for file_path in self.processed_dir.glob(f"*_{doc_id}.md"):
                    if file_path.exists():
                        # Read content for combined file
                        try:
                            content = file_path.read_text(encoding="utf-8")
                            result = next((r for r in results if r.document_id == doc_id), None)
                            
                            if result:
                                # Add section to combined markdown
                                combined_sections.append(f"# {result.filename}")
                                
                                if result.document_summary:
                                    combined_sections.extend(["", f"*{result.document_summary}*"])
                                
                                status_emoji = "✅" if result.pass_all_thresholds else "⚠️"
                                optimized_emoji = " 🎯" if result.vector_optimized else ""
                                
                                combined_sections.extend([
                                    "",
                                    f"**Processing Status:** {status_emoji} {'RAG Ready' if result.pass_all_thresholds else 'Needs Improvement'}{optimized_emoji}",
                                    f"**Conversion Score:** {result.conversion_score}/100"
                                ])
                                
                                if result.llm_evaluation:
                                    scores = [
                                        f"Clarity: {result.llm_evaluation.clarity_score or 'N/A'}/10",
                                        f"Completeness: {result.llm_evaluation.completeness_score or 'N/A'}/10",
                                        f"Relevance: {result.llm_evaluation.relevance_score or 'N/A'}/10",
                                        f"Markdown: {result.llm_evaluation.markdown_score or 'N/A'}/10"
                                    ]
                                    combined_sections.append(f"**Quality Scores:** {', '.join(scores)}")
                                
                                combined_sections.extend(["", "---", ""])
                                
                                # Adjust markdown hierarchy for combined document
                                adjusted_content = self._adjust_markdown_hierarchy(content)
                                combined_sections.extend([adjusted_content, "", "", "---", ""])
                        
                        except Exception as e:
                            print(f"Error reading {file_path}: {e}")
                        
                        # Add to ZIP as individual file
                        original_name = file_path.name.split('_', 1)[-1] if '_' in file_path.name else file_path.name
                        zipf.write(file_path, f"individual_files/{original_name}")
                        file_count += 1
                        break
            
            # Add combined markdown file
            if combined_sections:
                combined_content = "\n".join(combined_sections)
                combined_filename = f"COMBINED_EXPORT_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                zipf.writestr(combined_filename, combined_content)
            
            # Add summary file
            if file_count > 0:
                summary_content = self._generate_detailed_zip_summary(document_ids, results, file_count)
                summary_filename = f"PROCESSING_SUMMARY_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                zipf.writestr(summary_filename, summary_content)
        
        return zip_path, file_count
    
    def _adjust_markdown_hierarchy(self, content: str) -> str:
        """Adjust markdown headers by adding one level of nesting."""
        if not content:
            return content
        
        lines = content.split('\n')
        adjusted_lines = []
        
        for line in lines:
            # Check if line starts with markdown headers
            header_match = line.strip()
            if header_match.startswith('#') and not header_match.startswith('######'):
                # Find the header level
                header_level = 0
                for char in header_match:
                    if char == '#':
                        header_level += 1
                    else:
                        break
                
                if header_level < 6:  # Don't exceed maximum header depth
                    # Add one more # to increase nesting level
                    adjusted_line = '#' + line
                    adjusted_lines.append(adjusted_line)
                else:
                    adjusted_lines.append(line)
            else:
                adjusted_lines.append(line)
        
        return '\n'.join(adjusted_lines)
    
    def _generate_zip_summary(self, document_ids: List[str], file_count: int) -> str:
        """Generate a basic summary for ZIP archive."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        return f"""# Curatore Export Summary

**Export Details:**
- Generated: {timestamp}
- Documents Included: {file_count}
- Document IDs: {', '.join(document_ids)}

**Contents:**
- Individual processed markdown files in `processed_documents/` folder
- This summary file

**Usage:**
- Each `.md` file is ready for use in RAG systems
- Import into your vector database or knowledge base
- Files are optimized for semantic search and retrieval

---
*Generated by Curatore v2 - RAG Document Processing*
"""
    
    def _generate_detailed_zip_summary(
        self, 
        document_ids: List[str], 
        results: List[ProcessingResult], 
        file_count: int
    ) -> str:
        """Generate a detailed summary with processing results."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        successful_results = [r for r in results if r.success]
        rag_ready_results = [r for r in successful_results if r.pass_all_thresholds]
        vector_optimized_results = [r for r in successful_results if r.vector_optimized]
        pass_rate = (len(rag_ready_results) / len(successful_results) * 100) if successful_results else 0
        
        summary_lines = [
            "# Curatore Export Summary",
            f"**Generated:** {timestamp}",
            "",
            "## Export Overview",
            f"- Total Files Included: {file_count}",
            f"- Successfully Processed: {len(successful_results)}",
            f"- RAG Ready Files: {len(rag_ready_results)}",
            f"- Vector Optimized Files: {len(vector_optimized_results)}",
            f"- Overall Pass Rate: {pass_rate:.1f}%",
            "",
            "## Archive Contents",
            "- `individual_files/` - Individual processed markdown files",
            "- `COMBINED_EXPORT_*.md` - All documents combined into single file",
            "- `PROCESSING_SUMMARY_*.md` - This summary file",
            "",
            "## Processing Results",
            ""
        ]
        
        # Add detailed results for each document
        for result in successful_results:
            status = "RAG Ready ✅" if result.pass_all_thresholds else "Needs Improvement ⚠️"
            optimization = "Vector Optimized 🎯" if result.vector_optimized else "Standard Processing"
            
            summary_lines.extend([
                f"### {result.filename}",
                f"- **Status:** {status}",
                f"- **Processing:** {optimization}",
                f"- **Conversion Score:** {result.conversion_score}/100"
            ])
            
            if result.llm_evaluation:
                summary_lines.extend([
                    "- **Quality Scores:**",
                    f"  - Clarity: {result.llm_evaluation.clarity_score or 'N/A'}/10",
                    f"  - Completeness: {result.llm_evaluation.completeness_score or 'N/A'}/10",
                    f"  - Relevance: {result.llm_evaluation.relevance_score or 'N/A'}/10",
                    f"  - Markdown: {result.llm_evaluation.markdown_score or 'N/A'}/10"
                ])
            
            if result.document_summary:
                summary_lines.append(f"- **Summary:** {result.document_summary}")
            
            summary_lines.append("")
        
        summary_lines.extend([
            "## Usage Guidelines",
            "",
            "### For RAG Systems:",
            "1. Import RAG-ready files (marked with ✅) directly into your vector database",
            "2. Use the combined export for bulk import operations",
            "3. Files marked as 'Vector Optimized' have enhanced chunking structure",
            "",
            "### For Manual Review:",
            "1. Review files marked with ⚠️ before production use",
            "2. Check quality scores against your requirements",
            "3. Consider re-processing with adjusted thresholds if needed",
            "",
            "---",
            "*Generated by Curatore v2 - RAG Document Processing*"
        ])
        
        return "\n".join(summary_lines)
    
    def cleanup_zip_file(self, zip_path: str) -> bool:
        """Clean up temporary ZIP file."""
        try:
            if os.path.exists(zip_path):
                os.unlink(zip_path)
                return True
        except Exception as e:
            print(f"Error cleaning up ZIP file {zip_path}: {e}")
        return False


# Global ZIP service instance
zip_service = ZipService()