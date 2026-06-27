# RecruitIQ: Intelligent Candidate Ranking System

## 🚀 The Challenge
A high-performance candidate ranking engine built for the Redrob Intelligent Candidate Discovery & Ranking Challenge. The goal was to rank 100,000 candidates against a specific job description under strict compute (CPU-only) and memory constraints, while actively filtering out "honeypot" and low-quality data.

## 🧠 Our Architecture: The 3-Gate System
We opted for a deterministic, O(1) memory streaming pipeline to ensure reliability and speed:

1. **Gate 1: The Trap Door (Honeypot Filter)**
   - Eliminates logically impossible profiles (e.g., Skill duration > Total Experience).
   - Identifies keyword stuffers (non-technical titles with excessive AI keywords).
2. **Gate 2: The Ghost Filter (Behavioral Signals)**
   - Filters out candidates with < 20% recruiter response rates.
   - Drops inactive users who are not marked as "open to work".
3. **Gate 3: The Fast Math Scorer**
   - Ranks candidates using weighted skill matching, tiered education mapping, and normalizes scores using the `interview_completion_rate`.

## ⚡ Performance
- **Runtime:** ~26 seconds for 100,000 candidates.
- **Memory:** O(1) space complexity via `gzip` streaming.
- **Compute:** 100% CPU, 0 Network Calls during ranking.

## 🛠️ How to Reproduce
1. Ensure `candidates.jsonl.gz` is placed in the `data/` directory.
2. Run the ranker:
   ```bash
   python main.py
