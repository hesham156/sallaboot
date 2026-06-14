/// <reference types="vite/client" />

interface Window {
  fbAsyncInit?: () => void
  FB: {
    init(params: { appId: string; version: string; cookie?: boolean; xfbml?: boolean }): void
    login(callback: (response: { authResponse?: { accessToken: string } }) => void, options?: object): void
  }
}
