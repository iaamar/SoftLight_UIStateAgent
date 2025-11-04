'use client'

import { useState, useRef, useEffect } from 'react'

interface Message {
  id: string
  type: 'user' | 'assistant' | 'system' | 'login_required'
  content: string
  timestamp: Date
  screenshots?: string[]
  screenshot_metadata?: Array<{path: string, step_index: number, step_number: number | null}>
  step_descriptions?: string[]
  metadata?: any
  loginRequired?: {
    appName: string
    loginUrl: string
    originalTask: string
  }
}

interface ProgressUpdate {
  step: number
  total_steps: number
  description: string
  current_action?: string
}

function formatTime(date: Date): string {
  if (typeof window === 'undefined') return ''
  return date.toLocaleTimeString('en-US', { 
    hour: 'numeric', 
    minute: '2-digit',
    hour12: true 
  })
}

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      type: 'system',
      content: 'Welcome to SoftLight UI State Agent. I can help you capture UI states from any web application. Just tell me what you want to do!',
      timestamp: new Date()
    }
  ])
  const [input, setInput] = useState('')
  const [appUrl, setAppUrl] = useState('')
  const [appName, setAppName] = useState('')
  const [loading, setLoading] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [mounted, setMounted] = useState(false)
  const [selectedScreenshot, setSelectedScreenshot] = useState<{src: string, index: number, all: string[]} | null>(null)
  const [loginData, setLoginData] = useState<{
    email: string
    password: string
    appName: string
    appUrl: string
    originalTask: string
    oauthProviders?: string[]
    hasPasswordForm?: boolean
  } | null>(null)
  const [currentProgress, setCurrentProgress] = useState<ProgressUpdate | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    setMounted(true)
  }, [])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (selectedScreenshot) {
        if (e.key === 'Escape') {
          setSelectedScreenshot(null)
        } else if (e.key === 'ArrowLeft' && selectedScreenshot.index > 0) {
          setSelectedScreenshot({
            ...selectedScreenshot,
            index: selectedScreenshot.index - 1,
            src: selectedScreenshot.all[selectedScreenshot.index - 1]
          })
        } else if (e.key === 'ArrowRight' && selectedScreenshot.index < selectedScreenshot.all.length - 1) {
          setSelectedScreenshot({
            ...selectedScreenshot,
            index: selectedScreenshot.index + 1,
            src: selectedScreenshot.all[selectedScreenshot.index + 1]
          })
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedScreenshot])

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || loading) return

    const taskQuery = input
    const taskAppUrl = appUrl || 'https://www.notion.so'
    const taskAppName = appName || 'notion'
    
    const userMessage: Message = {
      id: Date.now().toString(),
      type: 'user',
      content: taskQuery,
      timestamp: new Date()
    }

    setMessages(prev => [...prev, userMessage])
    setInput('')
    setLoading(true)
    setCurrentProgress(null)

    // Connect to WebSocket for progress updates
    try {
      const ws = new WebSocket('ws://localhost:8000/ws/progress')
      wsRef.current = ws
      
      ws.onmessage = (event) => {
        try {
          const progress = JSON.parse(event.data) as ProgressUpdate
          setCurrentProgress(progress)
        } catch (e) {
          console.error('Failed to parse progress update:', e)
        }
      }
      
      ws.onerror = (error) => {
        console.error('WebSocket error:', error)
      }
      
      ws.onclose = () => {
        console.log('WebSocket closed')
      }
    } catch (e) {
      console.error('Failed to connect to WebSocket:', e)
    }

    try {
      const response = await fetch('http://localhost:8000/api/v1/execute', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          task_query: taskQuery,
          app_url: taskAppUrl,
          app_name: taskAppName,
        }),
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Request failed')
      }

      const data = await response.json()
      
      // Check if login is required
      if (data.requires_login) {
        const loginMessage: Message = {
          id: (Date.now() + 1).toString(),
          type: 'login_required',
          content: `🔐 Login required for ${data.app_name || taskAppName}`,
          timestamp: new Date(),
          loginRequired: {
            appName: data.app_name || taskAppName,
            loginUrl: data.login_url || taskAppUrl,
            originalTask: data.original_task || taskQuery
          }
        }
        setMessages(prev => [...prev, loginMessage])
        setLoginData({
          email: '',
          password: '',
          appName: data.app_name || taskAppName,
          appUrl: data.login_url || taskAppUrl,
          originalTask: data.original_task || taskQuery,
          oauthProviders: data.oauth_providers || [],
          hasPasswordForm: data.has_password_form || false
        })
        return
      }
      
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: data.success 
          ? `✅ Task completed successfully! Captured ${data.steps_completed} steps and ${data.screenshots?.length || 0} screenshots.`
          : `❌ Task failed: ${data.error || 'Unknown error'}`,
        timestamp: new Date(),
        screenshots: data.screenshots || [],
        screenshot_metadata: data.screenshot_metadata || [],
        step_descriptions: data.step_descriptions || [],
        metadata: data
      }

      setMessages(prev => [...prev, assistantMessage])
    } catch (error: any) {
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: `❌ Error: ${error.message}`,
        timestamp: new Date()
      }
      setMessages(prev => [...prev, errorMessage])
    } finally {
      setLoading(false)
      setCurrentProgress(null)
      // Close WebSocket connection
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }

  const handleLogin = async (email: string, password: string, method: string = "email_password") => {
    if (!loginData) return
    
    setLoading(true)
    
    try {
      const response = await fetch('http://localhost:8000/api/v1/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          email: method === "email_password" ? email : undefined,
          password: method === "email_password" ? password : undefined,
          app_name: loginData.appName,
          app_url: loginData.appUrl,
          original_task: loginData.originalTask,
          login_method: method
        }),
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Login failed')
      }

      const data = await response.json()
      
      if (data.success) {
        // Show success message
        const successMessage: Message = {
          id: (Date.now() + 1).toString(),
          type: 'assistant',
          content: '✅ Login successful! Resuming your task...',
          timestamp: new Date()
        }
        setMessages(prev => [...prev, successMessage])
        
        // If task result is included, show it
        if (data.task_result) {
          const taskMessage: Message = {
            id: (Date.now() + 2).toString(),
            type: 'assistant',
            content: data.task_result.success 
              ? `✅ Task completed successfully! Captured ${data.task_result.steps_completed} steps and ${data.task_result.screenshots?.length || 0} screenshots.`
              : `❌ Task failed: ${data.task_result.error || 'Unknown error'}`,
            timestamp: new Date(),
            screenshots: data.task_result.screenshots || [],
            screenshot_metadata: data.task_result.screenshot_metadata || [],
            step_descriptions: data.task_result.step_descriptions || [],
            metadata: data.task_result
          }
          setMessages(prev => [...prev, taskMessage])
        }
        
        setLoginData(null)
      }
    } catch (error: any) {
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: `❌ Login failed: ${error.message}`,
        timestamp: new Date()
      }
      setMessages(prev => [...prev, errorMessage])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] flex flex-col">
      <header className="border-b border-white/5 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <div className="relative">
              <div className="w-10 h-10 rounded-xl gradient-primary flex items-center justify-center shadow-lg glow-effect">
                <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <div className="absolute -top-1 -right-1 w-3 h-3 bg-green-500 rounded-full border-2 border-[#0a0a0a] animate-pulse"></div>
            </div>
            <div>
              <h1 className="text-xl font-bold text-white">SoftLight</h1>
              <p className="text-xs text-gray-400">UI State Agent</p>
            </div>
          </div>
          <button
            onClick={() => setShowSettings(!showSettings)}
            className="px-4 py-2 rounded-lg glass-morphism border border-white/10 text-gray-300 hover:text-white hover:border-white/20 transition-all text-sm"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </button>
        </div>
      </header>

      {showSettings && (
        <div className="border-b border-white/5 px-6 py-4 bg-black/20">
          <div className="max-w-7xl mx-auto">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-gray-400 mb-2 uppercase tracking-wider">App URL</label>
                <input
                  type="url"
                  value={appUrl}
                  onChange={(e) => setAppUrl(e.target.value)}
                  placeholder="https://www.notion.so"
                  className="w-full px-4 py-2 rounded-lg glass-morphism border border-white/10 focus:border-indigo-500/50 focus:ring-2 focus:ring-indigo-500/20 transition-all outline-none text-white placeholder:text-gray-500 bg-white/5 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-2 uppercase tracking-wider">App Name</label>
                <input
                  type="text"
                  value={appName}
                  onChange={(e) => setAppName(e.target.value)}
                  placeholder="notion"
                  className="w-full px-4 py-2 rounded-lg glass-morphism border border-white/10 focus:border-indigo-500/50 focus:ring-2 focus:ring-indigo-500/20 transition-all outline-none text-white placeholder:text-gray-500 bg-white/5 text-sm"
                />
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="flex-1 flex overflow-hidden">
        <main className="flex-1 flex flex-col max-w-7xl mx-auto w-full">
          <div className="flex-1 overflow-y-auto px-6 py-8 space-y-6">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`flex ${message.type === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-3xl rounded-2xl p-5 ${
                    message.type === 'user'
                      ? 'glass-strong border border-indigo-500/30 bg-indigo-500/10'
                      : message.type === 'system'
                      ? 'glass-morphism border border-white/10 bg-white/5'
                      : 'glass-strong border border-white/10 bg-white/5'
                  }`}
                >
                  <div className="flex items-start space-x-3">
                    {message.type !== 'user' && (
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                        message.type === 'system' ? 'bg-blue-500/20' : message.type === 'login_required' ? 'bg-yellow-500/20' : 'bg-purple-500/20'
                      }`}>
                        {message.type === 'system' ? (
                          <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                          </svg>
                        ) : message.type === 'login_required' ? (
                          <svg className="w-5 h-5 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                          </svg>
                        ) : (
                          <svg className="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                          </svg>
                        )}
                      </div>
                    )}
                    <div className="flex-1">
                      <p className={`text-sm leading-relaxed ${
                        message.type === 'user' ? 'text-white' : 'text-gray-200'
                      }`}>
                        {message.content}
                      </p>
                      {message.type === 'login_required' && message.loginRequired && loginData && (
                        <div className="mt-4 p-4 rounded-lg bg-yellow-500/10 border border-yellow-500/30">
                          <p className="text-sm text-yellow-200 mb-4">
                            🔐 Please choose a login method to continue:
                          </p>
                          <div className="space-y-3">
                            {/* OAuth Providers */}
                            {loginData.oauthProviders && loginData.oauthProviders.length > 0 && (
                              <div className="space-y-2">
                                <p className="text-xs text-yellow-300/80 mb-2 uppercase tracking-wider">Sign in with:</p>
                                {loginData.oauthProviders.map((provider) => (
                                  <button
                                    key={provider}
                                    onClick={() => handleLogin('', '', `oauth_${provider}`)}
                                    disabled={loading}
                                    className="w-full px-4 py-3 rounded-lg glass-morphism border border-white/10 hover:border-yellow-500/50 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2 text-white"
                                  >
                                    {provider === 'google' && (
                                      <>
                                        <svg className="w-5 h-5" viewBox="0 0 24 24">
                                          <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                                          <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                                          <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                                          <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                                        </svg>
                                        <span>Continue with Google</span>
                                      </>
                                    )}
                                    {provider === 'github' && (
                                      <>
                                        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                                          <path fillRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clipRule="evenodd"/>
                                        </svg>
                                        <span>Continue with GitHub</span>
                                      </>
                                    )}
                                    {provider === 'microsoft' && (
                                      <>
                                        <svg className="w-5 h-5" viewBox="0 0 23 23">
                                          <path fill="#f25022" d="M0 0h11.377v11.372H0z"/>
                                          <path fill="#00a4ef" d="M12.623 0H24v11.372H12.623z"/>
                                          <path fill="#7fba00" d="M0 12.628h11.377V24H0z"/>
                                          <path fill="#ffb900" d="M12.623 12.628H24V24H12.623z"/>
                                        </svg>
                                        <span>Continue with Microsoft</span>
                                      </>
                                    )}
                                  </button>
                                ))}
                                {loginData.hasPasswordForm && loginData.oauthProviders && loginData.oauthProviders.length > 0 && (
                                  <div className="flex items-center my-3">
                                    <div className="flex-1 border-t border-white/10"></div>
                                    <span className="px-3 text-xs text-gray-400">OR</span>
                                    <div className="flex-1 border-t border-white/10"></div>
                                  </div>
                                )}
                              </div>
                            )}
                            
                            {/* Email/Password Form */}
                            {loginData.hasPasswordForm && (
                              <>
                                <input
                                  type="email"
                                  placeholder="Email address"
                                  value={loginData.email}
                                  onChange={(e) => setLoginData({...loginData, email: e.target.value})}
                                  className="w-full px-4 py-3 rounded-lg glass-morphism border border-white/10 focus:border-yellow-500/50 focus:ring-2 focus:ring-yellow-500/20 transition-all outline-none text-white placeholder:text-gray-500 bg-white/5 text-sm"
                                  disabled={loading}
                                />
                                <input
                                  type="password"
                                  placeholder="Password"
                                  value={loginData.password}
                                  onChange={(e) => setLoginData({...loginData, password: e.target.value})}
                                  className="w-full px-4 py-3 rounded-lg glass-morphism border border-white/10 focus:border-yellow-500/50 focus:ring-2 focus:ring-yellow-500/20 transition-all outline-none text-white placeholder:text-gray-500 bg-white/5 text-sm"
                                  disabled={loading}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter' && loginData.email && loginData.password && !loading) {
                                      handleLogin(loginData.email, loginData.password, "email_password")
                                    }
                                  }}
                                />
                                <button
                                  onClick={() => handleLogin(loginData.email, loginData.password, "email_password")}
                                  disabled={loading || !loginData.email || !loginData.password}
                                  className="w-full px-4 py-3 rounded-lg bg-gradient-to-r from-yellow-500/80 to-yellow-600/80 hover:from-yellow-500 hover:to-yellow-600 text-white font-semibold shadow-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2"
                                >
                                  {loading ? (
                                    <>
                                      <svg className="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                      </svg>
                                      <span>Logging in...</span>
                                    </>
                                  ) : (
                                    <>
                                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1" />
                                      </svg>
                                      <span>Login with Email & Continue</span>
                                    </>
                                  )}
                                </button>
                              </>
                            )}
                            
                            {!loginData.hasPasswordForm && (!loginData.oauthProviders || loginData.oauthProviders.length === 0) && (
                              <p className="text-xs text-yellow-300/60 text-center">
                                No login methods detected. Please check the application URL.
                              </p>
                            )}
                            
                            {loginData.oauthProviders && loginData.oauthProviders.length > 0 && (
                              <p className="text-xs text-yellow-300/60 text-center mt-2">
                                A browser window will open for OAuth authentication. Complete the login there.
                              </p>
                            )}
                            
                            {loginData.hasPasswordForm && (
                              <p className="text-xs text-yellow-300/60 text-center mt-2">
                                Your credentials are secure and used only for authentication
                              </p>
                            )}
                          </div>
                        </div>
                      )}
                      {message.metadata && (
                        <div className="mt-4 space-y-3">
                          {message.metadata.steps_completed !== undefined && (
                            <div className="flex items-center space-x-4 text-xs text-gray-400">
                              <span className="flex items-center space-x-1">
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                                </svg>
                                <span>{message.metadata.steps_completed} steps</span>
                              </span>
                              {message.metadata.final_url && (
                                <a href={message.metadata.final_url} target="_blank" rel="noopener noreferrer" className="text-indigo-400 hover:text-indigo-300 flex items-center space-x-1">
                                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                                  </svg>
                                  <span>View URL</span>
                                </a>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                      {/* Show all steps as a list */}
                      {message.step_descriptions && message.step_descriptions.length > 0 && (
                        <div className="mt-4">
                          <p className="text-xs text-gray-400 mb-3 uppercase tracking-wider">
                            Workflow Steps ({message.step_descriptions.length})
                          </p>
                          <div className="space-y-2">
                            {message.step_descriptions.map((description, index) => {
                              // Check if this step has a screenshot using metadata mapping
                              const screenshotMetadata = message.screenshot_metadata?.find(m => m.step_index === index)
                              const hasScreenshot = !!screenshotMetadata
                              const screenshotIndex = hasScreenshot ? 
                                message.screenshots?.findIndex(s => s === screenshotMetadata?.path) ?? -1 : -1
                              
                              return (
                                <div
                                  key={index}
                                  className={`flex items-start space-x-3 p-3 rounded-lg border ${
                                    hasScreenshot 
                                      ? 'border-indigo-500/30 bg-indigo-500/5' 
                                      : 'border-white/10 bg-white/5'
                                  }`}
                                >
                                  <div className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold ${
                                    hasScreenshot 
                                      ? 'bg-indigo-500/20 text-indigo-300' 
                                      : 'bg-gray-500/20 text-gray-400'
                                  }`}>
                                    {index + 1}
                                  </div>
                                  <div className="flex-1 min-w-0">
                                    <p className="text-sm text-gray-200 leading-relaxed">
                                      {description}
                                    </p>
                                    {hasScreenshot && screenshotIndex >= 0 && (
                                      <button
                                        onClick={() => setSelectedScreenshot({
                                          src: `http://localhost:8000/api/v1/screenshot/${message.screenshots![screenshotIndex]}`,
                                          index: screenshotIndex,
                                          all: message.screenshots!.map(s => `http://localhost:8000/api/v1/screenshot/${s}`)
                                        })}
                                        className="mt-2 text-xs text-indigo-400 hover:text-indigo-300 flex items-center space-x-1"
                                      >
                                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                                        </svg>
                                        <span>View screenshot</span>
                                      </button>
                                    )}
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      )}
                      
                      {/* Show screenshots grid */}
                      {message.screenshots && message.screenshots.length > 0 && (
                        <div className="mt-4">
                          <p className="text-xs text-gray-400 mb-3 uppercase tracking-wider">
                            Screenshots ({message.screenshots.length})
                          </p>
                          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                            {message.screenshots.map((screenshot, screenshotIndex) => {
                              // Use metadata to find correct step mapping if available
                              const metadata = message.screenshot_metadata?.find(m => m.path === screenshot)
                              const stepIndex = metadata?.step_index ?? screenshotIndex
                              const description = message.step_descriptions?.[stepIndex] || 
                                                 message.step_descriptions?.[screenshotIndex] || 
                                                 `Step ${stepIndex + 1}`
                              
                              return (
                                <div
                                  key={screenshotIndex}
                                  className="group relative rounded-lg overflow-hidden border border-white/10 hover:border-indigo-500/50 transition-all cursor-pointer hover:scale-105 transform duration-200 flex flex-col"
                                >
                                  <div
                                    onClick={() => setSelectedScreenshot({
                                      src: `http://localhost:8000/api/v1/screenshot/${screenshot}`,
                                      index: screenshotIndex,
                                      all: message.screenshots!.map(s => `http://localhost:8000/api/v1/screenshot/${s}`)
                                    })}
                                    className="aspect-video bg-gradient-to-br from-indigo-500/10 to-purple-500/10 flex items-center justify-center group-hover:from-indigo-500/20 group-hover:to-purple-500/20 transition-all relative overflow-hidden rounded-lg"
                                  >
                                    <img
                                      src={`http://localhost:8000/api/v1/screenshot/${screenshot}`}
                                      alt={description}
                                      className="w-full h-full object-cover absolute inset-0"
                                      onError={(e) => {
                                        const target = e.target as HTMLImageElement
                                        target.style.display = 'none'
                                      }}
                                      onLoad={(e) => {
                                        const target = e.target as HTMLImageElement
                                        const placeholder = target.nextElementSibling as HTMLElement
                                        if (placeholder) placeholder.style.display = 'none'
                                      }}
                                    />
                                    <div className="absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-br from-indigo-500/10 to-purple-500/10 pointer-events-none z-10">
                                      <svg className="w-12 h-12 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                                      </svg>
                                      <p className="text-xs text-gray-400 mt-2">Step {stepIndex + 1}</p>
                                    </div>
                                    <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-all flex items-center justify-center pointer-events-none">
                                      <svg className="w-8 h-8 text-white opacity-0 group-hover:opacity-100 transition-opacity" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v3m0 0v3m0-3h3m-3 0H7" />
                                      </svg>
                                    </div>
                                  </div>
                                  <div className="p-3 bg-white/5 rounded-b-lg border-t border-white/10">
                                    <p className="text-xs text-gray-300 line-clamp-2 leading-relaxed" title={description}>
                                      <span className="text-indigo-400 font-semibold block mb-1">Step {stepIndex + 1}</span>
                                      <span className="text-gray-200">{description}</span>
                                    </p>
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      )}
                      {mounted && (
                        <p className="text-xs text-gray-500 mt-3">
                          {formatTime(message.timestamp)}
                        </p>
                      )}
                    </div>
                    {message.type === 'user' && (
                      <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center flex-shrink-0 ml-3">
                        <span className="text-white text-sm font-semibold">U</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="glass-morphism border border-white/10 rounded-2xl p-5 max-w-3xl">
                  <div className="flex items-start space-x-3">
                    <div className="w-8 h-8 rounded-lg bg-purple-500/20 flex items-center justify-center flex-shrink-0">
                      <svg className="animate-spin h-5 w-5 text-purple-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                    </div>
                    <div className="flex-1">
                      <p className="text-gray-300 font-medium mb-2">Processing your request...</p>
                      {currentProgress && (
                        <div className="mt-3 space-y-2">
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-gray-400">Progress</span>
                            <span className="text-indigo-400">
                              Step {currentProgress.step} of {currentProgress.total_steps || '?'}
                            </span>
                          </div>
                          {currentProgress.total_steps && (
                            <div className="w-full bg-white/10 rounded-full h-2 overflow-hidden">
                              <div 
                                className="bg-gradient-to-r from-indigo-500 to-purple-500 h-full transition-all duration-300"
                                style={{ width: `${(currentProgress.step / currentProgress.total_steps) * 100}%` }}
                              />
                            </div>
                          )}
                          <p className="text-sm text-gray-300 mt-2">
                            {currentProgress.current_action || currentProgress.description || 'Analyzing...'}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="border-t border-white/5 px-6 py-4">
            <form onSubmit={handleSend} className="max-w-7xl mx-auto">
              <div className="flex items-end space-x-4">
                <div className="flex-1">
                  <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="Ask me to capture UI states... (e.g., How do I create a project in Notion?)"
                    className="w-full px-5 py-4 rounded-xl glass-morphism border border-white/10 focus:border-indigo-500/50 focus:ring-2 focus:ring-indigo-500/20 transition-all outline-none text-white placeholder:text-gray-500 bg-white/5 backdrop-blur-sm hover:bg-white/10"
                    disabled={loading}
                  />
                </div>
                <button
                  type="submit"
                  disabled={loading || !input.trim()}
                  className="px-6 py-4 rounded-xl gradient-primary text-white font-semibold shadow-lg glow-effect hover-glow transform transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed disabled:transform-none flex items-center justify-center space-x-2"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                  </svg>
                </button>
              </div>
            </form>
          </div>
        </main>
      </div>

      {/* Screenshot Modal/Lightbox */}
      {selectedScreenshot && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-sm p-4"
          onClick={() => setSelectedScreenshot(null)}
        >
          <div className="relative max-w-7xl max-h-full w-full h-full flex items-center justify-center">
            {/* Close Button */}
            <button
              onClick={() => setSelectedScreenshot(null)}
              className="absolute top-4 right-4 z-10 p-3 rounded-full glass-morphism border border-white/20 hover:border-white/40 transition-all text-white hover:bg-white/10"
              aria-label="Close"
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>

            {/* Navigation Arrows */}
            {selectedScreenshot.index > 0 && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedScreenshot({
                    ...selectedScreenshot,
                    index: selectedScreenshot.index - 1,
                    src: selectedScreenshot.all[selectedScreenshot.index - 1]
                  })
                }}
                className="absolute left-4 z-10 p-3 rounded-full glass-morphism border border-white/20 hover:border-white/40 transition-all text-white hover:bg-white/10"
                aria-label="Previous"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
              </button>
            )}

            {selectedScreenshot.index < selectedScreenshot.all.length - 1 && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedScreenshot({
                    ...selectedScreenshot,
                    index: selectedScreenshot.index + 1,
                    src: selectedScreenshot.all[selectedScreenshot.index + 1]
                  })
                }}
                className="absolute right-4 z-10 p-3 rounded-full glass-morphism border border-white/20 hover:border-white/40 transition-all text-white hover:bg-white/10"
                aria-label="Next"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </button>
            )}

            {/* Screenshot Image */}
            <div 
              className="relative w-full h-full flex items-center justify-center"
              onClick={(e) => e.stopPropagation()}
            >
              <img
                src={selectedScreenshot.src}
                alt={`Screenshot ${selectedScreenshot.index + 1}`}
                className="max-w-full max-h-full object-contain rounded-lg shadow-2xl"
              />
            </div>

            {/* Step Counter */}
            <div className="absolute bottom-4 left-1/2 transform -translate-x-1/2 glass-morphism border border-white/20 px-4 py-2 rounded-full text-white text-sm">
              Step {selectedScreenshot.index + 1} of {selectedScreenshot.all.length}
            </div>

            {/* Keyboard Hint */}
            <div className="absolute bottom-4 right-4 glass-morphism border border-white/20 px-3 py-1 rounded text-white text-xs opacity-60">
              Use ← → arrows or ESC to close
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
