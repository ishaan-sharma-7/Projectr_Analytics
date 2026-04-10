import { useState, useRef, useEffect, useCallback } from "react";
import { Send, Bot, User, Loader2, Hexagon } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { HousingPressureScore } from "../../lib/api";
import type { HexFeatureProperties } from "../../lib/hexApi";

const HEX_ACTION_RE = /\[\[SELECT_HEX:([a-f0-9]+)\]\]/g;

/** Strip [[SELECT_HEX:...]] markers from text so ReactMarkdown doesn't render them raw. */
function stripHexActions(text: string): string {
  return text.replace(HEX_ACTION_RE, "").replace(/\n{3,}/g, "\n\n");
}

/** Extract all h3 indices from [[SELECT_HEX:...]] markers. */
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

export function ChatbotWidget({ selectedName, activeScore, selectedHex, onUniversityScored, onSelectHex }: ChatbotWidgetProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([{
    role: "assistant",
    content: "Hi! I'm your CampusLens analyst. I can discuss housing pressure scores, hex-level development opportunities, compare markets, or analyze any US university — even ones not yet in the database. Ask me anything."
  }]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom of messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const generateResponse = async (currentHistory: ChatMessage[]): Promise<{ text: string; newlyScored: HousingPressureScore | null }> => {
    try {
      const baseUrl = "http://localhost:8000";
      const payload = {
        messages: currentHistory,
        selectedName: selectedName || null,
        activeScore: activeScore || null,
        selectedHex: selectedHex || null,
      };

      const controller = new AbortController();
      // Allow up to 2 minutes for responses that trigger scoring pipelines
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
        return { text: "The analysis timed out. This can happen when scoring a new university with slow data sources. Try asking again.", newlyScored: null };
      }
      console.error("Chat error:", err);
      return { text: "Looks like I'm having trouble reaching the server right now. Make sure the backend is running!", newlyScored: null };
    }
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";

    // Add user message immediately
    const userMsg: ChatMessage = { role: "user", content: userMessage };
    const newHistory = [...messages, userMsg];
    setMessages(newHistory);
    setIsLoading(true);

    // Fetch assistant response asynchronously
    const result = await generateResponse(newHistory);

    setMessages(prev => [...prev, { role: "assistant", content: result.text }]);
    setIsLoading(false);

    if (result.newlyScored && onUniversityScored) {
      onUniversityScored(result.newlyScored);
    }
  };

  return (
    <div className="flex-1 flex flex-col bg-zinc-950 overflow-hidden text-zinc-100">

      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-4 bg-zinc-950 border-b border-zinc-800 shrink-0">
        <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center">
          <Bot className="w-5 h-5 text-white" />
        </div>
        <div>
          <h3 className="font-semibold text-sm">CampusLens Assistant</h3>
          <p className="text-xs text-zinc-400">Context: {selectedName || "All universities"}</p>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-6">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex gap-3 ${msg.role === "assistant" ? "items-start" : "items-center flex-row-reverse"}`}
          >
            <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
              msg.role === "assistant" ? "bg-blue-600/20 text-blue-400" : "bg-zinc-800 text-zinc-400"
            }`}>
              {msg.role === "assistant" ? <Bot className="w-4 h-4" /> : <User className="w-4 h-4" />}
            </div>

            <div className={`text-sm px-4 py-3 rounded-2xl max-w-[85%] ${
              msg.role === "assistant"
                ? "bg-zinc-900 border border-zinc-800/50 rounded-tl-none prose prose-invert prose-sm"
                : "bg-blue-600 text-white rounded-tr-none"
            }`}>
              {msg.role === "assistant" ? (
                <>
                  <ReactMarkdown>{stripHexActions(msg.content)}</ReactMarkdown>
                  {extractHexActions(msg.content).length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2 not-prose">
                      {extractHexActions(msg.content).map((h3Id) => (
                        <button
                          key={h3Id}
                          onClick={() => onSelectHex?.(h3Id)}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-blue-600/20 text-blue-400 text-xs font-mono hover:bg-blue-600/40 transition-colors cursor-pointer border border-blue-500/30"
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

        {/* Typing indicator */}
        {isLoading && (
          <div className="flex gap-3 items-start">
            <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 bg-blue-600/20 text-blue-400">
              <Bot className="w-4 h-4" />
            </div>
            <div className="text-sm px-4 py-3 rounded-2xl rounded-tl-none bg-zinc-900 border border-zinc-800/50 text-zinc-400 flex items-center gap-2">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              <span>Analyzing...</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input field */}
      <form
        onSubmit={handleSend}
        className="p-4 bg-zinc-950 border-t border-zinc-800 flex items-end gap-3 shrink-0"
      >
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            // Auto-resize
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
          placeholder={isLoading ? "Waiting for response..." : "Ask about markets, hexes, parcels, comparisons..."}
          disabled={isLoading}
          rows={1}
          className="flex-1 bg-zinc-900 border border-zinc-700/50 rounded-xl px-4 py-3 text-sm text-zinc-100 focus:outline-none focus:border-blue-500 transition-colors placeholder:text-zinc-500 shadow-inner disabled:opacity-50 resize-none overflow-y-auto"
          style={{ maxHeight: 160 }}
        />
        <button
          type="submit"
          disabled={!input.trim() || isLoading}
          className="w-11 h-11 flex items-center justify-center bg-blue-600 text-white rounded-xl hover:bg-blue-500 transition-colors disabled:opacity-50 disabled:hover:bg-blue-600 shadow-md shrink-0"
        >
          <Send className="w-5 h-5 ml-0.5" />
        </button>
      </form>
    </div>
  );
}
