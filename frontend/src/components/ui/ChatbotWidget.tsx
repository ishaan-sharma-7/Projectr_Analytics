import { useState, useRef, useEffect } from "react";
import { Send, Bot, User, Loader2, Hexagon } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { HousingPressureScore } from "../../lib/api";
import type { HexFeatureProperties } from "../../lib/hexApi";

const HEX_ACTION_RE = /\[\[SELECT_HEX:([a-f0-9]+)\]\]/g;

function stripHexActions(text: string): string {
  return text.replace(HEX_ACTION_RE, "").replace(/\n{3,}/g, "\n\n");
}

function extractHexActions(text: string): string[] {
  const ids: string[] = [];
  let m;
  while ((m = HEX_ACTION_RE.exec(text)) !== null) ids.push(m[1]);
  return ids;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface ChatbotWidgetProps {
  selectedName: string | null;
  activeScore: HousingPressureScore | null;
  selectedHex: HexFeatureProperties | null;
  onUniversityScored?: (score: HousingPressureScore) => void;
  onSelectHex?: (h3Index: string) => void;
}

export function ChatbotWidget({
  selectedName,
  activeScore,
  selectedHex,
  onUniversityScored,
  onSelectHex,
}: ChatbotWidgetProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content:
        "Hi! I'm your CampusLens analyst. I can discuss housing pressure scores, hex-level development opportunities, compare markets, or analyze any US university — even ones not yet in the database. Ask me anything.",
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const generateResponse = async (
    currentHistory: ChatMessage[],
  ): Promise<{ text: string; newlyScored: HousingPressureScore | null }> => {
    try {
      const baseUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";
      const payload = {
        messages: currentHistory,
        selectedName: selectedName || null,
        activeScore: activeScore || null,
        selectedHex: selectedHex || null,
      };

      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 120_000);

      const res = await fetch(`${baseUrl}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      clearTimeout(timeout);

      if (!res.ok) throw new Error("API error");
      const data = await res.json();
      return { text: data.response, newlyScored: data.newly_scored ?? null };
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return {
          text: "The analysis timed out. This can happen when scoring a new university with slow data sources. Try asking again.",
          newlyScored: null,
        };
      }
      console.error("Chat error:", err);
      return {
        text: "Looks like I'm having trouble reaching the server right now. Make sure the backend is running!",
        newlyScored: null,
      };
    }
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";

    const userMsg: ChatMessage = { role: "user", content: userMessage };
    const newHistory = [...messages, userMsg];
    setMessages(newHistory);
    setIsLoading(true);

    const result = await generateResponse(newHistory);

    setMessages((prev) => [
      ...prev,
      { role: "assistant", content: result.text },
    ]);
    setIsLoading(false);

    if (result.newlyScored && onUniversityScored) {
      onUniversityScored(result.newlyScored);
    }
  };

  return (
    <div
      className="flex-1 flex flex-col overflow-hidden"
      style={{ background: "var(--bg)" }}
    >
      {/* Header */}
      <div
        className="flex items-center gap-3 px-5 py-4 shrink-0"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
        >
          <Bot className="w-4 h-4" style={{ color: "var(--text-2)" }} />
        </div>
        <div>
          <h3
            className="font-semibold text-sm"
            style={{ fontFamily: "'Inter Tight', sans-serif", color: "var(--text)", letterSpacing: "-0.02em" }}
          >
            CampusLens Assistant
          </h3>
          <p className="text-xs" style={{ color: "var(--text-3)" }}>
            {selectedName || "All universities"}
          </p>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-5">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex gap-3 ${msg.role === "user" ? "flex-row-reverse" : ""}`}
          >
            <div
              className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
              style={{
                background: "var(--surface-2)",
                border: "1px solid var(--border)",
              }}
            >
              {msg.role === "assistant" ? (
                <Bot className="w-3.5 h-3.5" style={{ color: "var(--text-3)" }} />
              ) : (
                <User className="w-3.5 h-3.5" style={{ color: "var(--text-3)" }} />
              )}
            </div>

            <div
              className={`text-sm px-4 py-3 rounded-xl max-w-[85%] ${
                msg.role === "assistant"
                  ? "prose prose-invert prose-sm"
                  : ""
              }`}
              style={
                msg.role === "assistant"
                  ? {
                      background: "var(--surface)",
                      border: "1px solid var(--border)",
                      color: "var(--text-2)",
                    }
                  : {
                      background: "var(--surface-2)",
                      border: "1px solid var(--border)",
                      color: "var(--text)",
                    }
              }
            >
              {msg.role === "assistant" ? (
                <>
                  <ReactMarkdown>{stripHexActions(msg.content)}</ReactMarkdown>
                  {extractHexActions(msg.content).length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2 not-prose">
                      {extractHexActions(msg.content).map((h3Id) => (
                        <button
                          key={h3Id}
                          onClick={() => onSelectHex?.(h3Id)}
                          className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md font-mono text-xs transition-colors"
                          style={{
                            background: "var(--surface-2)",
                            border: "1px solid var(--border)",
                            color: "var(--text-2)",
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.borderColor = "var(--border-hover)";
                            e.currentTarget.style.color = "var(--text)";
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.borderColor = "var(--border)";
                            e.currentTarget.style.color = "var(--text-2)";
                          }}
                          title={`Select hex ${h3Id} on map`}
                        >
                          <Hexagon className="w-3 h-3" />
                          {h3Id.slice(-8)}
                        </button>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                msg.content
              )}
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex gap-3">
            <div
              className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
              style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
            >
              <Bot className="w-3.5 h-3.5" style={{ color: "var(--text-3)" }} />
            </div>
            <div
              className="text-sm px-4 py-3 rounded-xl flex items-center gap-2"
              style={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                color: "var(--text-3)",
              }}
            >
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              <span>Analyzing...</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form
        onSubmit={handleSend}
        className="p-4 flex items-end gap-3 shrink-0"
        style={{ borderTop: "1px solid var(--border)" }}
      >
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            const el = e.target;
            el.style.height = "auto";
            el.style.height = Math.min(el.scrollHeight, 160) + "px";
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSend(e);
            }
          }}
          placeholder={
            isLoading
              ? "Waiting for response..."
              : "Ask about markets, hexes, parcels..."
          }
          disabled={isLoading}
          rows={1}
          className="flex-1 text-sm outline-none resize-none overflow-y-auto rounded-xl px-4 py-3 transition-colors disabled:opacity-50"
          style={{
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
            color: "var(--text)",
            maxHeight: 160,
          }}
          onFocus={(e) =>
            (e.currentTarget.style.borderColor = "var(--border-hover)")
          }
          onBlur={(e) =>
            (e.currentTarget.style.borderColor = "var(--border)")
          }
        />
        <button
          type="submit"
          disabled={!input.trim() || isLoading}
          className="btn-ql btn-ql-primary disabled:opacity-40 shrink-0"
          style={{ padding: "9px" }}
        >
          <span className="btn-icon" style={{ margin: 0 }}>
            <Send className="w-3.5 h-3.5" />
          </span>
        </button>
      </form>
    </div>
  );
}
