"use client";

import { useEffect, useRef, useState } from "react";
import { startCrawl, getCrawlStatus, resumeCrawl, cancelCrawl, downloadUrl, CrawlStatus } from "@/lib/api";

const ACTIVE_STATUSES = new Set(["pending", "discovering", "crawling"]);

export default function Home() {
  const [url, setUrl] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<CrawlStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!jobId) return;
    const poll = async () => {
      try {
        const s = await getCrawlStatus(jobId);
        setStatus(s);
        if (!ACTIVE_STATUSES.has(s.status) && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch (e: any) {
        setError(e.message);
      }
    };
    poll();
    pollRef.current = setInterval(poll, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [jobId]);

  const handleCancel = async () => {
    if (!jobId) return;
    try {
      await cancelCrawl(jobId);
      setStatus(prev => prev ? { ...prev, status: "cancelled" } : null);
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleStart = async () => {
    setError(null);
    if (!url.trim()) {
      setError("Enter a website URL first.");
      return;
    }
    setStarting(true);
    try {
      const res = await startCrawl(url.trim());
      setJobId(res.job_id);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setStarting(false);
    }
  };

  const handleResume = async () => {
    if (!jobId) return;
    try {
      await resumeCrawl(jobId);
      pollRef.current = setInterval(async () => {
        const s = await getCrawlStatus(jobId);
        setStatus(s);
        if (!ACTIVE_STATUSES.has(s.status) && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      }, 2000);
    } catch (e: any) {
      setError(e.message);
    }
  };

  const reset = () => {
    setJobId(null);
    setStatus(null);
    setUrl("");
    setError(null);
  };

  return (
    <main className="max-w-2xl mx-auto px-4 py-16">
      <h1 className="text-3xl font-bold mb-1">Website Blog Extractor</h1>
      <p className="text-slate-500 mb-8">
        Paste a website URL. We&apos;ll find every blog post and hand you an Excel/CSV.
      </p>

      {!jobId && (
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
          <label className="block text-sm font-medium text-slate-700 mb-2">
            Enter website URL
          </label>
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com"
            className="w-full border border-slate-300 rounded-lg px-4 py-3 mb-4 focus:outline-none focus:ring-2 focus:ring-blue-500"
            onKeyDown={(e) => e.key === "Enter" && handleStart()}
          />
          <button
            onClick={handleStart}
            disabled={starting}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-semibold rounded-lg py-3 transition"
          >
            {starting ? "Starting..." : "Start Blog Extraction"}
          </button>
          {error && <p className="text-red-600 text-sm mt-3">{error}</p>}
        </div>
      )}

      {status && ACTIVE_STATUSES.has(status.status) && (
        <ProgressCard status={status} onCancel={handleCancel} />
      )}

      {status && status.status === "paused" && (
        <div className="bg-white rounded-xl shadow-sm border border-amber-300 p-6">
          <h2 className="text-xl font-semibold text-amber-700 mb-2">Extraction Paused</h2>
          <p className="text-slate-600 mb-4">
            {status.blogs_processed} of {status.blogs_identified} blogs processed so far. You can
            resume without losing progress.
          </p>
          <button
            onClick={handleResume}
            className="bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg px-5 py-2.5"
          >
            Resume Extraction
          </button>
        </div>
      )}

      {status && status.status === "failed" && (
        <div className="bg-white rounded-xl shadow-sm border border-red-300 p-6">
          <h2 className="text-xl font-semibold text-red-700 mb-2">Extraction Failed</h2>
          <p className="text-slate-600 mb-4">{status.error_message || "An unexpected error occurred."}</p>
          <div className="flex gap-3">
            <button onClick={handleResume} className="bg-slate-700 hover:bg-slate-800 text-white font-semibold rounded-lg px-5 py-2.5">
              Retry
            </button>
            <button onClick={reset} className="border border-slate-300 rounded-lg px-5 py-2.5">
              Start Over
            </button>
          </div>
        </div>
      )}

      {(status?.status === "completed" || status?.status === "cancelled") && (
        <CompletedCard status={status} onReset={reset} />
      )}
    </main>
  );
}

function ProgressCard({ status, onCancel }: { status: CrawlStatus, onCancel: () => void }) {
  const label =
    status.status === "discovering" ? "Discovering blog URLs..." : "Extracting blog content...";
  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <div className="flex justify-between items-start mb-1">
        <h2 className="text-xl font-semibold">Extraction in Progress</h2>
        <button 
          onClick={onCancel}
          className="text-sm font-medium text-red-600 hover:text-red-700 hover:bg-red-50 px-3 py-1.5 rounded-lg transition-colors border border-transparent hover:border-red-200"
        >
          Stop Extraction
        </button>
      </div>
      <p className="text-slate-500 mb-4">{status.website_url}</p>

      <div className="w-full bg-slate-100 rounded-full h-3 mb-2 overflow-hidden">
        <div
          className="bg-blue-600 h-3 rounded-full transition-all duration-500"
          style={{ width: `${Math.max(status.progress_percent, 3)}%` }}
        />
      </div>
      <p className="text-sm text-slate-500 mb-6">{label} &middot; {status.progress_percent}%</p>

      <div className="grid grid-cols-2 gap-4 mb-6">
        <Stat label="URLs Found" value={status.urls_discovered} />
        <Stat label="Blogs Found" value={status.blogs_identified} />
        <Stat label="Processed" value={status.blogs_processed} />
        <Stat label="Remaining" value={status.remaining} />
        <Stat label="Successful" value={status.blogs_successful} color="text-green-600" />
        <Stat label="Failed" value={status.blogs_failed} color="text-red-600" />
      </div>

      {status.current_url && (
        <div className="text-xs text-slate-400 truncate">
          Current URL: <span className="text-slate-600">{status.current_url}</span>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div className="bg-slate-50 rounded-lg p-3">
      <div className={`text-2xl font-bold ${color || "text-slate-800"}`}>{value.toLocaleString()}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}

function CompletedCard({ status, onReset }: { status: CrawlStatus; onReset: () => void }) {
  const isCancelled = status.status === "cancelled";
  const title = isCancelled ? "Extraction Stopped" : "Extraction Completed";
  const titleColor = isCancelled ? "text-slate-700" : "text-green-700";
  const borderColor = isCancelled ? "border-slate-300" : "border-green-300";

  return (
    <div className={`bg-white rounded-xl shadow-sm border ${borderColor} p-6`}>
      <h2 className={`text-xl font-semibold ${titleColor} mb-1`}>{title}</h2>
      <p className="text-slate-500 mb-6">{status.website_url}</p>

      <div className="grid grid-cols-3 gap-4 mb-6">
        <Stat label="Total Blogs" value={status.blogs_identified} />
        <Stat label="Successful" value={status.blogs_successful} color="text-green-600" />
        <Stat label="Failed" value={status.blogs_failed} color="text-red-600" />
      </div>

      <div className="flex flex-wrap gap-3 mb-4">
        <a href={downloadUrl(status.job_id, "excel")} className="bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg px-5 py-2.5">
          Download Excel
        </a>
        <a href={downloadUrl(status.job_id, "csv")} className="bg-slate-700 hover:bg-slate-800 text-white font-semibold rounded-lg px-5 py-2.5">
          Download CSV
        </a>
        <a href={downloadUrl(status.job_id, "failed")} className="border border-slate-300 rounded-lg px-5 py-2.5">
          Download Failed URLs
        </a>
      </div>

      <button onClick={onReset} className="text-sm text-slate-500 underline">
        Extract another website
      </button>
    </div>
  );
}
