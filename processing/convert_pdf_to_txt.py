import os
import re
import PyPDF2


def is_empty_page(page_text):
    """
    Check if a page is truly empty (no content at all).
    
    Args:
        page_text: Extracted text from a page
        
    Returns:
        bool: True if page is completely empty
    """
    if not page_text:
        return True
    
    # Remove all whitespace and check if there's any content
    cleaned_text = re.sub(r'\s+', '', page_text.strip())
    
    # Only consider it empty if there's absolutely no content
    if len(cleaned_text) == 0:
        return True
    
    return False


def is_table_of_contents_page(page_text, page_num, total_pages):
    """
    Detect if a page is a table of contents page anywhere in the document.
    
    Args:
        page_text: Extracted text from a page
        page_num: Zero-indexed page number
        total_pages: Total number of pages in the PDF
        
    Returns:
        bool: True if page is likely a TOC page
    """
    if not page_text:
        return False
    
    cleaned_text = page_text.lower().strip()
    
    # Common TOC indicators (check anywhere in document, not just beginning)
    toc_keywords = [
        'table of contents',
        'contents',
        'table des matières',
        'índice',
        'inhoudsopgave',
    ]
    
    # Check for TOC keywords
    for keyword in toc_keywords:
        if keyword in cleaned_text:
            # Additional check: TOC pages often have patterns like "Chapter 1 ... 5"
            # or numbered lists with dots or page numbers
            toc_patterns = [
                r'\d+\s*\.\.\.\s*\d+',  # Numbers ... numbers (page references)
                r'chapter\s+\d+',  # Chapter X
                r'section\s+\d+',  # Section X
                r'^\d+[\.\)]\s+[^\n]+',  # Numbered list items at start of lines
            ]
            
            pattern_matches = sum(1 for pattern in toc_patterns if re.search(pattern, cleaned_text, re.MULTILINE | re.IGNORECASE))
            
            # If we find TOC keyword and at least one pattern, it's likely a TOC
            if pattern_matches > 0:
                return True
    
    # Check for TOC-like patterns even without explicit keywords
    # Lines with page numbers at the end (common TOC format)
    lines = cleaned_text.split('\n')
    lines_with_page_refs = 0
    for line in lines:
        # Check if line ends with a page number
        if re.search(r'\s+\d+\s*$', line.strip()):
            lines_with_page_refs += 1
    
    # If more than 3 lines have page references, it's likely TOC (regardless of position)
    if lines_with_page_refs >= 3:
        return True
    
    return False


def is_preface_or_foreword_page(page_text):
    """
    Detect if a page is a preface or foreword page anywhere in the document.
    
    Args:
        page_text: Extracted text from a page
        
    Returns:
        bool: True if page is likely a preface/foreword page
    """
    if not page_text:
        return False
    
    cleaned_text = page_text.lower().strip()
    
    # Preface/foreword indicators
    preface_keywords = [
        'preface',
        'foreword',
        'avant-propos',
        'prólogo',
    ]
    
    for keyword in preface_keywords:
        # Check if keyword appears in the text (not just as part of another word)
        # Use word boundaries or check if it's a standalone word/phrase
        if re.search(r'\b' + re.escape(keyword) + r'\b', cleaned_text, re.IGNORECASE):
            return True
    
    return False


def is_introduction_page(page_text):
    """
    Detect if a page is an introduction page anywhere in the document.
    
    Args:
        page_text: Extracted text from a page
        
    Returns:
        bool: True if page is likely an introduction page
    """
    if not page_text:
        return False
    
    cleaned_text = page_text.lower().strip()
    
    # Introduction indicators
    intro_keywords = [
        'introduction',
        'intro',
        'introducción',
        'inleiding',
    ]
    
    # Check if "introduction" appears as a heading/title (more likely to be an intro page)
    # This helps avoid false positives when "introduction" appears in actual content
    intro_patterns = [
        r'^introduction\s*$',  # Standalone "Introduction" at start of page
        r'^introduction\s*:',  # "Introduction:" at start
        r'\nintroduction\s*\n',  # "Introduction" as a heading
        r'\bintroduction\b',  # Word boundary check
    ]
    
    for keyword in intro_keywords:
        for pattern in intro_patterns:
            pattern_escaped = pattern.replace('introduction', keyword)
            if re.search(pattern_escaped, cleaned_text, re.MULTILINE | re.IGNORECASE):
                # Additional check: if it's a heading-like format, more likely to be intro page
                if 'chapter' not in cleaned_text[:200] and 'section' not in cleaned_text[:200]:
                    return True
    
    return False


def is_authors_note_page(page_text):
    """
    Detect if a page is an author's note page anywhere in the document.
    
    Args:
        page_text: Extracted text from a page
        
    Returns:
        bool: True if page is likely an author's note page
    """
    if not page_text:
        return False
    
    cleaned_text = page_text.lower().strip()
    
    # Author's note indicators
    author_note_keywords = [
        "author's note",
        "author note",
        "author's note:",
        "author note:",
        "notes from the author",
        "note from the author",
        "author's preface",
        "note de l'auteur",
        "nota del autor",
    ]
    
    for keyword in author_note_keywords:
        # Check if keyword appears in the text
        if keyword in cleaned_text:
            return True
    
    # Also check for patterns like "Author: [name]" followed by note-like content
    if re.search(r'author\s*:', cleaned_text) and len(cleaned_text) < 2000:
        # Short page with author mention might be author's note
        if 'note' in cleaned_text[:500] or 'acknowledgment' in cleaned_text[:500]:
            return True
    
    return False


def is_non_medical_page(page_text):
    """
    Detect if a page contains non-medical content (acknowledgments, dedication, etc.).
    This is a helper function to identify pages that shouldn't be in medical KB.
    
    Args:
        page_text: Extracted text from a page
        
    Returns:
        bool: True if page is likely non-medical administrative content
    """
    if not page_text:
        return False
    
    cleaned_text = page_text.lower().strip()
    
    # Non-medical page indicators
    non_medical_keywords = [
        'acknowledgment',
        'acknowledgements',
        'dedication',
        'copyright',
        'publisher\'s note',
        'publishers note',
        'about the author',
        'about the authors',
        'biography',
        'bibliography',
    ]
    
    for keyword in non_medical_keywords:
        # Check if keyword appears prominently (likely a heading)
        if re.search(r'\b' + re.escape(keyword) + r'\b', cleaned_text, re.IGNORECASE):
            # If it's a short page or appears as a heading, likely non-medical
            if len(cleaned_text) < 1500 or re.search(r'^' + re.escape(keyword), cleaned_text, re.MULTILINE | re.IGNORECASE):
                return True
    
    return False


def is_contributor_page(page_text):
    """
    Detect if a page is a contributor/credits page anywhere in the document.
    
    Args:
        page_text: Extracted text from a page
        
    Returns:
        bool: True if page is likely a contributor/credits page
    """
    if not page_text:
        return False
    
    cleaned_text = page_text.lower().strip()
    
    # Contributor page indicators
    contributor_keywords = [
        'contributors',
        'contributor',
        'credits',
        'credit',
        'author contributions',
        'contributing authors',
        'editorial team',
        'writing team',
        'expert panel',
        'advisory committee',
    ]
    
    # Check for contributor keywords
    for keyword in contributor_keywords:
        if re.search(r'\b' + re.escape(keyword) + r'\b', cleaned_text, re.IGNORECASE):
            # Additional check: Contributor pages often have numbered lists of people
            # Look for patterns like "1. Dr.", "2. Prof.", etc.
            contributor_patterns = [
                r'^\d+\.\s*(dr\.|prof\.|mr\.|ms\.|mrs\.)',  # Numbered list with titles
                r'\d+\.\s*(dr\.|prof\.|mr\.|ms\.|mrs\.)',  # Numbered list with titles (anywhere)
            ]
            
            for pattern in contributor_patterns:
                if re.search(pattern, cleaned_text, re.MULTILINE | re.IGNORECASE):
                    return True
    
    # Also check if page has many "Dr.", "Prof." titles which indicate contributor lists
    title_count = len(re.findall(r'\b(dr\.|prof\.|mr\.|ms\.|mrs\.|director|professor)\b', cleaned_text, re.IGNORECASE))
    # If more than 5 titles and page mentions contributor-related terms, likely contributor page
    if title_count >= 5 and any(keyword in cleaned_text for keyword in ['contributor', 'credit', 'author', 'editorial', 'advisory']):
        return True
    
    return False


def clean_partial_tables(text):
    """
    Clean up partial/broken tables from extracted text.
    Tables in PDFs often get fragmented during extraction, creating broken text patterns.
    
    Args:
        text: Extracted text that may contain partial tables
        
    Returns:
        str: Cleaned text with partial tables removed or fixed
    """
    if not text:
        return text
    
    lines = text.split('\n')
    cleaned_lines = []
    
    for line in lines:
        # Skip lines that are likely broken table fragments
        stripped_line = line.strip()
        
        # Skip empty lines
        if not stripped_line:
            cleaned_lines.append('')
            continue
        
        # Detect partial table patterns:
        # 1. Lines with excessive consecutive spaces (table columns often have many spaces)
        if re.search(r' {4,}', stripped_line):
            # Check if it looks like table data (has multiple spaced fragments)
            fragments = [f for f in stripped_line.split() if f]
            # If many short fragments separated by spaces, likely a table row
            if len(fragments) > 5 and all(len(f) < 30 for f in fragments[:5]):
                # Skip this line as it's likely a broken table row
                continue
        
        # 2. Lines with concatenated text that looks like table overflow
        # Pattern: text without spaces between words, then numbers/text merged
        if re.search(r'[a-zA-Z]+\d+[a-zA-Z]+', stripped_line):
            # Check if it's a short fragment (likely broken table cell)
            if len(stripped_line.split()) < 3:
                continue
        
        # 3. Lines with many numbers separated by spaces (table data)
        # But we want to keep legitimate number lists, so check for excessive whitespace
        number_separated = re.findall(r'\d+\s{2,}\d+', stripped_line)
        if len(number_separated) >= 3:
            # Likely a table with numeric data
            # Only remove if it has very little text content
            text_content = re.sub(r'\d+\s*', '', stripped_line)
            if len(text_content.strip()) < 20:
                continue
        
        # 4. Lines with text fragments that appear concatenated (common in broken tables)
        # Example: "word1word2" or "Dr.  Name, Title, Institution12. Dr."
        # Pattern: Text immediately followed by number then more text (like "Jharkhnad6. Dr.")
        if re.search(r'[a-zA-Z]{4,}\d+\.?\s*[A-Z]', stripped_line):
            # If line is short and has this pattern, likely broken
            if len(stripped_line) < 150:
                continue
        
        # 5. Lines with multiple consecutive titles (Dr., Prof.) that look fragmented
        # Pattern like "Dr.  Name, Title, Institution12. Dr. Another Name"
        if re.search(r'Dr\.\s{2,}[A-Z]', stripped_line) and len(re.findall(r'Dr\.', stripped_line)) >= 2:
            # If line has multiple Dr. titles with excessive spacing, likely broken table
            if len(stripped_line) < 200:
                continue
        
        # Keep the line if it doesn't match problematic patterns
        cleaned_lines.append(line)
    
    # Join lines back
    cleaned_text = '\n'.join(cleaned_lines)
    
    # Additional cleanup: Remove lines that are just numbers or very short fragments
    # that appear isolated (likely table artifacts)
    final_lines = []
    for line in cleaned_text.split('\n'):
        stripped = line.strip()
        # Skip lines that are just numbers or very short isolated fragments
        if stripped and re.match(r'^\d+\.?\s*$', stripped):
            continue
        # Skip very short lines that are just fragments (likely table artifacts)
        if len(stripped) < 5 and stripped and not re.match(r'^[A-Z][a-z]+$', stripped):
            # But keep common short words
            if stripped.lower() not in ['no', 'yes', 'ok', 'etc', 'and', 'or', 'the', 'a', 'an']:
                continue
        final_lines.append(line)
    
    return '\n'.join(final_lines)


def clean_pdf_pages(pdf_reader):
    """
    Identify which pages should be removed by evaluating all pages.
    Removes: empty pages, TOC, preface/foreword, introduction, author's note, 
    contributor pages, and non-medical pages.
    
    Args:
        pdf_reader: PyPDF2 PdfReader object
        
    Returns:
        list: List of page indices to keep (0-indexed)
    """
    total_pages = len(pdf_reader.pages)
    pages_to_keep = []
    
    for page_num in range(total_pages):
        page = pdf_reader.pages[page_num]
        page_text = page.extract_text()
        
        # Skip empty pages
        if is_empty_page(page_text):
            print(f"Skipping empty page {page_num + 1}")
            continue
        
        # Skip TOC pages (checked anywhere in document)
        if is_table_of_contents_page(page_text, page_num, total_pages):
            print(f"Skipping table of contents page {page_num + 1}")
            continue
        
        # Skip preface/foreword pages (checked anywhere in document)
        if is_preface_or_foreword_page(page_text):
            print(f"Skipping preface/foreword page {page_num + 1}")
            continue
        
        # Skip introduction pages (checked anywhere in document)
        if is_introduction_page(page_text):
            print(f"Skipping introduction page {page_num + 1}")
            continue
        
        # Skip author's note pages (checked anywhere in document)
        if is_authors_note_page(page_text):
            print(f"Skipping author's note page {page_num + 1}")
            continue
        
        # Skip non-medical pages (checked anywhere in document)
        if is_non_medical_page(page_text):
            print(f"Skipping non-medical page {page_num + 1}")
            continue
        
        # Skip contributor pages (checked anywhere in document)
        if is_contributor_page(page_text):
            print(f"Skipping contributor page {page_num + 1}")
            continue
        
        pages_to_keep.append(page_num)
    
    return pages_to_keep


def convert_pdf_to_txt(pdf_path, txt_path):
    """
    Convert PDF to text file, removing empty pages, TOC, preface/foreword, 
    introduction, author's note, contributor pages, non-medical pages, and partial tables.
    Evaluates all pages through a pipeline to determine which are useful for KB creation.
    
    Args:
        pdf_path: Path to input PDF file
        txt_path: Path to output text file
    """
    # Open the PDF file in read-binary mode
    with open(pdf_path, 'rb') as pdf_file:
        # Create a PDF file reader object
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        
        print(f"Processing PDF: {os.path.basename(pdf_path)}")
        print(f"Total pages: {len(pdf_reader.pages)}")
        
        # Clean PDF: evaluate all pages and identify which to keep
        pages_to_keep = clean_pdf_pages(pdf_reader)
        
        # Format page numbers for output (1-indexed, with ranges if applicable)
        if pages_to_keep:
            page_ranges = []
            start = pages_to_keep[0]
            end = pages_to_keep[0]
            
            for i in range(1, len(pages_to_keep)):
                if pages_to_keep[i] == end + 1:
                    end = pages_to_keep[i]
                else:
                    if start == end:
                        page_ranges.append(str(start + 1))
                    else:
                        page_ranges.append(f"{start + 1}-{end + 1}")
                    start = pages_to_keep[i]
                    end = pages_to_keep[i]
            
            # Add the last range
            if start == end:
                page_ranges.append(str(start + 1))
            else:
                page_ranges.append(f"{start + 1}-{end + 1}")
            
            print(f"Pages to process: [{', '.join(page_ranges)}]")
        
        print(f"Total pages to process: {len(pages_to_keep)} (removed {len(pdf_reader.pages) - len(pages_to_keep)} pages)")
        
        # Initialize an empty string to hold the extracted text
        text = ''
        
        # Loop through only the pages we want to keep
        for page_num in pages_to_keep:
            page = pdf_reader.pages[page_num]
            page_text = page.extract_text()
            if page_text.strip():
                text += page_text + '\n\n'  # Add spacing between pages
        
        # Clean up partial/broken tables from the extracted text
        text = clean_partial_tables(text)
        
        # Write the extracted text to the output text file
        with open(txt_path, 'w', encoding='utf-8') as txt_file:
            txt_file.write(text)
        
        print(f"Successfully converted to: {os.path.basename(txt_path)}")

pdf_folder_path = os.path.join(os.environ['APP_PATH'], os.environ['DATA_PATH'], 'raw_documents_pdf')
txt_folder_path = os.path.join(os.environ['APP_PATH'], os.environ['DATA_PATH'], 'raw_documents')

os.makedirs(txt_folder_path, exist_ok=True)

for pdf_file_name in os.listdir(pdf_folder_path):
    pdf_file_path = os.path.join(pdf_folder_path, pdf_file_name)
    txt_file_path = os.path.join(txt_folder_path, pdf_file_name.replace('.pdf', '.txt'))
    convert_pdf_to_txt(pdf_file_path, txt_file_path)