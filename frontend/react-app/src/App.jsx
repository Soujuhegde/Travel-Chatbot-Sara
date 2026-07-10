import React from 'react';
import ChatInterface from './components/ChatInterface';

function App() {
  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
      <div className="w-[80%] max-w-[1600px] h-[90vh] glass rounded-3xl overflow-hidden flex flex-col">
        <header className="bg-brand text-white p-6 shadow-md z-10 flex justify-between items-center">
          <div>
            <h1 className="text-2xl font-bold tracking-wide">TravelBot</h1>
            <p className="text-brand-light text-sm">Your intelligent travel companion</p>
          </div>
          <div className="bg-brand-dark px-4 py-2 rounded-full text-sm font-medium">
            Demo Mode
          </div>
        </header>

        <main className="flex-1 overflow-hidden relative">
          <ChatInterface />
        </main>
      </div>
    </div>
  );
}

export default App;
