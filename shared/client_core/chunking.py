"""
BeezClient File Chunking Utilities

Provides functions for splitting files into chunks and reassembling them.
Chunk size is 1MB to keep chunk counts reasonable for large files.
"""

from typing import List, BinaryIO

# Default chunk size: 1MB (aligned with BeezClient / pricing_config)
DEFAULT_CHUNK_SIZE = 1024 * 1024


def split_file(file_content: bytes, chunk_size: int = DEFAULT_CHUNK_SIZE) -> List[bytes]:
    """
    Split file content into chunks of specified size.
    
    Args:
        file_content: File bytes to split
        chunk_size: Size of each chunk in bytes (default: 100KB)
        
    Returns:
        List of chunk bytes
    """
    return [file_content[i:i + chunk_size] for i in range(0, len(file_content), chunk_size)]


def split_file_in_chunks(file: BinaryIO, chunk_size: int = DEFAULT_CHUNK_SIZE) -> List[bytes]:
    """
    Split a file object into chunks (no padding).
    
    Args:
        file: File object opened in binary mode
        chunk_size: Size of each chunk in bytes
        
    Returns:
        List of chunk bytes
    """
    chunks = []
    while True:
        chunk = file.read(chunk_size)
        if not chunk:
            break
        chunks.append(chunk)
    return chunks


def split_file_in_chunks_with_padding(file: BinaryIO, chunk_size: int = DEFAULT_CHUNK_SIZE) -> List[bytes]:
    """
    Split a file object into chunks with null-byte padding on the last chunk.
    
    Args:
        file: File object opened in binary mode
        chunk_size: Size of each chunk in bytes
        
    Returns:
        List of chunk bytes (last chunk padded to chunk_size)
    """
    chunks = []
    while True:
        chunk = file.read(chunk_size)
        if not chunk:
            break
        if len(chunk) < chunk_size:
            chunk += b'\x00' * (chunk_size - len(chunk))
        chunks.append(chunk)
    return chunks


def concatenate_chunks(chunks: List[bytes]) -> bytes:
    """
    Concatenate chunks back into a single file content.
    
    Args:
        chunks: List of chunk bytes
        
    Returns:
        Concatenated file content
    """
    return b"".join(chunks)


def split_encrypted_file_in_chunks(file_path: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> List[bytes]:
    """
    Split an encrypted file into chunks without decrypting.
    
    Important: For block ciphers like AES, chunk_size should be a multiple
    of the block size (16 bytes) to avoid decryption errors.
    
    Args:
        file_path: Path to the encrypted file
        chunk_size: Size of each chunk (should be multiple of 16 for AES)
        
    Returns:
        List of chunk bytes
    """
    chunks = []
    try:
        with open(file_path, 'rb') as file:
            while True:
                chunk = file.read(chunk_size)
                if not chunk:
                    break
                chunks.append(chunk)
    except FileNotFoundError:
        print(f"[CHUNKING] Error: File '{file_path}' does not exist.", flush=True)
    except Exception as e:
        print(f"[CHUNKING] Error reading file: {e}", flush=True)
    
    return chunks


def calculate_num_chunks(file_size: int, chunk_size: int = DEFAULT_CHUNK_SIZE) -> int:
    """
    Calculate the number of chunks needed for a file.
    
    Args:
        file_size: Size of the file in bytes
        chunk_size: Size of each chunk in bytes
        
    Returns:
        Number of chunks
    """
    return (file_size + chunk_size - 1) // chunk_size


def remove_padding(data: bytes, original_size: int) -> bytes:
    """
    Remove padding from reassembled data.
    
    Args:
        data: Padded data
        original_size: Original file size before padding
        
    Returns:
        Data with padding removed
    """
    return data[:original_size]
