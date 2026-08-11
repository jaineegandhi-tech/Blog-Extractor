const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export type JobStatus =
  | "pending" | "discovering" | "crawling" | "completed"
  | "failed" | "paused" | "cancelled";

export interface CrawlStatus {
  job_id: string;
  website_url: string;
  status: JobStatus;
  urls_discovered: number;
  blogs_identified: number;
  blogs_processed: number;
  blogs_successful: number;
  blogs_failed: number;
  remaining: number;
  progress_percent: number;
  total_words_extracted: number;
  current_url: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  exports_ready: boolean;
}

export async function startCrawl(url: string): Promise<{ job_id: string; status: string }> {
  const res = await fetch(`${API_URL}/crawl`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Failed to start crawl (${res.status})`);
  }
  return res.json();
}

export async function getCrawlStatus(jobId: string): Promise<CrawlStatus> {
  const res = await fetch(`${API_URL}/crawl/${jobId}`);
  if (!res.ok) throw new Error(`Failed to fetch status (${res.status})`);
  return res.json();
}

export async function resumeCrawl(jobId: string): Promise<{ job_id: string; status: string }> {
  const res = await fetch(`${API_URL}/crawl/${jobId}/resume`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to resume crawl (${res.status})`);
  return res.json();
}

export async function cancelCrawl(jobId: string): Promise<{ job_id: string; status: string }> {
  const res = await fetch(`${API_URL}/crawl/${jobId}/cancel`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to cancel crawl (${res.status})`);
  return res.json();
}

export function downloadUrl(jobId: string, kind: "excel" | "csv" | "failed"): string {
  if (kind === "failed") return `${API_URL}/crawl/${jobId}/failed`;
  return `${API_URL}/crawl/${jobId}/download/${kind}`;
}
