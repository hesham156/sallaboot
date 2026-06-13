import { useEffect } from 'react'

interface SEO {
  title:        string
  description?: string
  canonical?:   string
  noindex?:     boolean
}

/**
 * Per-page SEO helper. Sets the document <title>, the meta description,
 * the canonical URL and (optionally) a robots noindex flag for the
 * page that mounts it. Restores nothing on unmount — the next page
 * sets its own values.
 *
 * The static defaults in index.html cover the landing page; this hook
 * is what every other page uses to differentiate its <title> in Google
 * SERPs and social previews.
 */
export function useSEO({ title, description, canonical, noindex }: SEO) {
  useEffect(() => {
    document.title = title

    // Meta description
    if (description) {
      let el = document.querySelector<HTMLMetaElement>('meta[name="description"]')
      if (!el) {
        el = document.createElement('meta')
        el.setAttribute('name', 'description')
        document.head.appendChild(el)
      }
      el.setAttribute('content', description)
    }

    // Open Graph title (mirror page title so WhatsApp previews stay correct)
    let ogTitle = document.querySelector<HTMLMetaElement>('meta[property="og:title"]')
    if (!ogTitle) {
      ogTitle = document.createElement('meta')
      ogTitle.setAttribute('property', 'og:title')
      document.head.appendChild(ogTitle)
    }
    ogTitle.setAttribute('content', title)

    if (description) {
      let ogDesc = document.querySelector<HTMLMetaElement>('meta[property="og:description"]')
      if (!ogDesc) {
        ogDesc = document.createElement('meta')
        ogDesc.setAttribute('property', 'og:description')
        document.head.appendChild(ogDesc)
      }
      ogDesc.setAttribute('content', description)
    }

    // Canonical URL — defaults to the current path on 7ayak.app
    const canonicalHref = canonical || `https://7ayak.app${window.location.pathname}`
    let link = document.querySelector<HTMLLinkElement>('link[rel="canonical"]')
    if (!link) {
      link = document.createElement('link')
      link.setAttribute('rel', 'canonical')
      document.head.appendChild(link)
    }
    link.setAttribute('href', canonicalHref)

    // og:url mirrors canonical
    let ogUrl = document.querySelector<HTMLMetaElement>('meta[property="og:url"]')
    if (!ogUrl) {
      ogUrl = document.createElement('meta')
      ogUrl.setAttribute('property', 'og:url')
      document.head.appendChild(ogUrl)
    }
    ogUrl.setAttribute('content', canonicalHref)

    // Robots
    let robots = document.querySelector<HTMLMetaElement>('meta[name="robots"]')
    if (!robots) {
      robots = document.createElement('meta')
      robots.setAttribute('name', 'robots')
      document.head.appendChild(robots)
    }
    robots.setAttribute('content', noindex ? 'noindex, nofollow' : 'index, follow, max-image-preview:large')
  }, [title, description, canonical, noindex])
}
