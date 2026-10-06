use regex::Regex;

pub fn split_into_rag_chunks(content: &str, chunk_size: usize, overlap: usize, min_chunk: usize) -> Vec<String> {
    let content = content.trim();
    if content.is_empty() {
        return Vec::new();
    }
    if content.len() <= chunk_size {
        return vec![content.to_string()];
    }
    let paragraphs = split_paragraphs(content);
    let raw = accumulate(&paragraphs, chunk_size);
    let mut split = Vec::new();
    for chunk in raw {
        if chunk.len() <= chunk_size {
            split.push(chunk);
        } else {
            split.extend(split_long(&chunk, chunk_size));
        }
    }
    let overlapped = add_overlap(split, overlap);
    let result: Vec<String> = overlapped
        .into_iter()
        .filter(|c| c.trim().len() >= min_chunk)
        .collect();
    if result.is_empty() {
        vec![content.chars().take(chunk_size).collect()]
    } else {
        result
    }
}

fn split_sentences(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let chars: Vec<char> = text.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        cur.push(chars[i]);
        if matches!(chars[i], '.' | '!' | '?') {
            let mut j = i + 1;
            while j < chars.len() && chars[j].is_whitespace() {
                j += 1;
            }
            if j > i + 1 && j < chars.len() {
                out.push(cur.trim().to_string());
                cur.clear();
                i = j;
                continue;
            }
        }
        i += 1;
    }
    if !cur.trim().is_empty() {
        out.push(cur.trim().to_string());
    }
    if out.is_empty() {
        out.push(text.to_string());
    }
    out
}

fn split_paragraphs(text: &str) -> Vec<String> {
    let re = Regex::new(r"\n\s*\n").unwrap();
    re.split(text)
        .map(|p| p.trim().to_string())
        .filter(|p| !p.is_empty())
        .collect()
}

fn accumulate(segments: &[String], max_size: usize) -> Vec<String> {
    let mut chunks = Vec::new();
    let mut current = String::new();
    for segment in segments {
        if !current.is_empty() && current.len() + segment.len() + 1 > max_size {
            chunks.push(current.trim().to_string());
            current = segment.clone();
        } else if current.is_empty() {
            current = segment.clone();
        } else {
            current.push_str("\n\n");
            current.push_str(segment);
        }
    }
    if !current.trim().is_empty() {
        chunks.push(current.trim().to_string());
    }
    chunks
}

fn split_long(text: &str, max_size: usize) -> Vec<String> {
    let sentences: Vec<String> = split_sentences(text);
    if sentences.len() > 1 {
        let mut result = Vec::new();
        for chunk in accumulate(&sentences, max_size) {
            if chunk.len() <= max_size {
                result.push(chunk);
            } else {
                result.extend(split_on_words(&chunk, max_size));
            }
        }
        return result;
    }
    split_on_words(text, max_size)
}

fn add_overlap(chunks: Vec<String>, overlap: usize) -> Vec<String> {
    if overlap == 0 || chunks.len() <= 1 {
        return chunks;
    }
    let mut result = vec![chunks[0].clone()];
    for i in 1..chunks.len() {
        let prev = &chunks[i - 1];
        let mut overlap_text = suffix_on_char_boundary(prev, overlap).to_string();
        if let Some(idx) = overlap_text.find(' ') {
            if idx > 0 && overlap_text.is_char_boundary(idx + 1) {
                overlap_text = overlap_text[idx + 1..].to_string();
            }
        }
        result.push(format!("{} {}", overlap_text, chunks[i]));
    }
    result
}

fn suffix_on_char_boundary(s: &str, max_bytes: usize) -> &str {
    if s.len() <= max_bytes {
        return s;
    }
    let mut i = s.len().saturating_sub(max_bytes);
    while i < s.len() && !s.is_char_boundary(i) {
        i += 1;
    }
    &s[i..]
}

fn split_on_words(text: &str, max_size: usize) -> Vec<String> {
    let mut chunks = Vec::new();
    let mut current = String::new();
    for word in text.split_whitespace() {
        if word.len() > max_size {
            if !current.trim().is_empty() {
                chunks.push(current.trim().to_string());
                current.clear();
            }
            chunks.extend(split_by_chars(word, max_size));
            continue;
        }
        if !current.is_empty() && current.len() + word.len() + 1 > max_size {
            chunks.push(current.trim().to_string());
            current = word.to_string();
        } else if current.is_empty() {
            current = word.to_string();
        } else {
            current.push(' ');
            current.push_str(word);
        }
    }
    if !current.trim().is_empty() {
        chunks.push(current.trim().to_string());
    }
    chunks
}

fn split_by_chars(text: &str, max_size: usize) -> Vec<String> {
    let mut out = Vec::new();
    let mut buf = String::new();
    for ch in text.chars() {
        let mut tmp = [0u8; 4];
        let piece = ch.encode_utf8(&mut tmp);
        if !buf.is_empty() && buf.len() + piece.len() > max_size {
            out.push(buf);
            buf = String::new();
        }
        buf.push(ch);
    }
    if !buf.is_empty() {
        out.push(buf);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn short_text_one_chunk() {
        let c = split_into_rag_chunks("hello world", 800, 100, 50);
        assert_eq!(c, vec!["hello world"]);
    }

    #[test]
    fn em_dash_does_not_panic() {
        let dash = "—";
        let text = format!("{} {}", "word ".repeat(80), dash.repeat(40));
        let chunks = split_into_rag_chunks(&text, 80, 30, 10);
        assert!(!chunks.is_empty());
    }
}
