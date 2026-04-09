import { useState, useRef, useEffect } from "react";
import { Send, Bot, User } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { HousingPressureScore } from "../../lib/api";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface ChatbotWidgetProps {
  selectedName: string | null;
  activeScore: HousingPressureScore | null;
}

export function ChatbotWidget({ selectedName, activeScore }: ChatbotWidgetProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([{
    role: "assistant",
    content: "Hi! I'm your analytical assistant. I can explain housing pressure scores, interpret metrics, or help you compare markets."
  }]);
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom of messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const generateResponse = async (currentHistory: ChatMessage[]): Promise<string> => {
    try {
      const baseUrl = "http://localhost:8000";
      const payload = {
        messages: currentHistory,
        selectedName: selectedName || null,
        activeScore: activeScore || null
      };

      const res = await fetch(`${baseUrl}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error("API error");
      const data = await res.json();
      return data.response;
    } catch (err) {
      console.error("Chat error:", err);
      return "Looks like I'm having trouble reaching the server right now. Make sure the backend is running!";
    }
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    const userMessage = input.trim();
    setInput("");
    
    // Add user message immediately
    const userMsg: ChatMessage = { role: "user", content: userMessage };
    const newHistory = [...messages, userMsg];
    setMessages(newHistory);

    // Fetch assistant response asynchronously by sending the active history
    const responseContent = await generateResponse(newHistory);
    
    setMessages(prev => [...prev, { role: "assistant", content: responseContent }]);
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
          <p className="text-xs text-zinc-400">Context: {selectedName || "General"}</p>
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
                <ReactMarkdown>{msg.content}</ReactMarkdown>
              ) : (
                msg.content
              )}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input field */}
      <form 
        onSubmit={handleSend}
        className="p-4 bg-zinc-950 border-t border-zinc-800 flex items-center gap-3 shrink-0"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about this data..."
          className="flex-1 bg-zinc-900 border border-zinc-700/50 rounded-xl px-4 py-3 text-sm text-zinc-100 focus:outline-none focus:border-blue-500 transition-colors placeholder:text-zinc-500 shadow-inner"
        />
        <button 
          type="submit"
          disabled={!input.trim()}
          className="w-11 h-11 flex items-center justify-center bg-blue-600 text-white rounded-xl hover:bg-blue-500 transition-colors disabled:opacity-50 disabled:hover:bg-blue-600 shadow-md"
        >
          <Send className="w-5 h-5 ml-0.5" />
        </button>
      </form>
    </div>
  );
}
