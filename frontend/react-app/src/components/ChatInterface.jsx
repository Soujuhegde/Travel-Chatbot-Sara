import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import { Send, MapPin } from 'lucide-react';
import MessageBubble from './MessageBubble';
import TypingIndicator from './TypingIndicator';

// Simple random string generator
const generateId = () => Math.random().toString(36).substring(2, 15);

const ChatInterface = () => {
  const [messages, setMessages] = useState([
    {
      id: 1,
      sender: 'bot',
      text: 'Hi there! I am your AI travel assistant. I can help you find flights and hotels. Where would you like to go?',
    }
  ]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [sessionId, setSessionId] = useState(generateId());
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  const sendMessage = async (text) => {
    if (!text.trim()) return;

    const userMessage = {
      id: Date.now(),
      sender: 'user',
      text: text.trim()
    };
    
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsTyping(true);

    try {
      const response = await axios.post('http://localhost:8000/api/chat', {
        message: userMessage.text,
        session_id: sessionId
      });

      const botMessage = {
        id: Date.now() + 1,
        sender: 'bot',
        text: response.data.message,
        options: response.data.options,
        quick_replies: response.data.quick_replies,
        ticket: response.data.ticket
      };

      setMessages(prev => [...prev, botMessage]);
    } catch (error) {
      console.error("Error communicating with chat API:", error);
      const errorMessage = {
        id: Date.now() + 1,
        sender: 'bot',
        text: "I'm sorry, I'm having trouble connecting to my servers right now."
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleSend = (e) => {
    e.preventDefault();
    sendMessage(input);
  };

  const samplePrompts = [
    "Flights to Goa this weekend",
    "Hotels near Marina Beach Chennai",
    "I want to go to Tokyo in June"
  ];

  const isInitialState = messages.length === 1;

  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return "Good morning";
    if (hour < 18) return "Good afternoon";
    return "Good evening";
  };

  if (isInitialState) {
    return (
      <div className="flex flex-col h-full bg-slate-50/50 items-center justify-center p-6">
        <div className="w-full max-w-3xl flex flex-col items-center animate-fade-in-up">
          <h2 className="text-4xl font-serif text-gray-800 mb-8">{getGreeting()}, how can I help you?</h2>
          
          <form onSubmit={handleSend} className="relative flex items-center w-full mb-8 shadow-lg rounded-full">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Where would you like to travel today?"
              className="w-full pl-8 pr-16 py-5 rounded-full border border-gray-200 focus:border-brand focus:ring-2 focus:ring-brand/20 outline-none text-gray-700 text-lg transition-all"
              disabled={isTyping}
            />
            <button
              type="submit"
              disabled={!input.trim() || isTyping}
              className="absolute right-3 p-3.5 bg-brand text-white rounded-full hover:bg-brand-dark disabled:opacity-50 disabled:hover:bg-brand transition-colors shadow-md"
            >
              <Send className="w-6 h-6" />
            </button>
          </form>

          <div className="flex flex-wrap justify-center gap-3 w-full">
            {samplePrompts.map((prompt, idx) => (
              <button
                key={idx}
                onClick={() => setInput(prompt)}
                className="px-5 py-2.5 bg-white border border-gray-200 text-gray-600 rounded-full text-sm font-medium hover:bg-gray-50 transition-colors flex items-center gap-2 shadow-sm"
              >
                <MapPin className="w-4 h-4 text-brand" />
                {prompt}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-slate-50/50">
      <div className="flex-1 overflow-y-auto p-6 scroll-smooth">
        {messages.map((msg) => (
          <MessageBubble 
            key={msg.id} 
            message={msg} 
            onQuickReply={sendMessage} 
            onOptionSelect={(option, flightClass, price) => {
              sendMessage(`I would like to select ${flightClass} class on ${option.airline_name} ${option.flight_numbers} for ${price}`);
            }}
          />
        ))}
        {isTyping && (
          <div className="mb-6">
            <TypingIndicator />
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="p-4 bg-white border-t border-slate-200">
        <form onSubmit={handleSend} className="relative flex items-center">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type your travel request here..."
            className="w-full pl-6 pr-14 py-4 rounded-full border border-slate-200 focus:border-brand focus:ring-2 focus:ring-brand/20 outline-none text-slate-700 shadow-sm transition-all"
            disabled={isTyping}
          />
          <button
            type="submit"
            disabled={!input.trim() || isTyping}
            className="absolute right-2 p-3 bg-brand text-white rounded-full hover:bg-brand-dark disabled:opacity-50 disabled:hover:bg-brand transition-colors shadow-md"
          >
            <Send className="w-5 h-5" />
          </button>
        </form>
      </div>
    </div>
  );
};

export default ChatInterface;
