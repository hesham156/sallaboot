import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useSEO } from '../hooks/useSEO'
import { POSTS } from '../content/blog/posts'

function formatDate(iso: string): string {
  // Display as DD MMM YYYY in Arabic — Intl handles the month name.
  try {
    return new Intl.DateTimeFormat('ar-SA', {
      year: 'numeric', month: 'long', day: 'numeric',
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

export default function BlogList() {
  const navigate = useNavigate()
  useSEO({
    title:       'مدونة حياك — دليلك الشامل لإدارة متجر سلة وزيادة المبيعات',
    description: 'مقالات عملية للتجار: ربط بوت واتساب، استرجاع السلات المتروكة، تحسين تجربة العميل، وأفضل ممارسات التجارة الإلكترونية في السوق السعودي.',
  })

  return (
    <div dir="rtl" className="min-h-screen bg-slate-50/50 text-slate-800 font-sans pb-20 overflow-x-hidden">
      {/* Background glows */}
      <div className="absolute top-[-6rem] right-[-6rem] w-[34rem] h-[34rem] bg-teal-300/20 rounded-full blur-[130px] pointer-events-none" />
      <div className="absolute top-[10rem] left-[-8rem] w-[30rem] h-[30rem] bg-cyan-300/15 rounded-full blur-[130px] pointer-events-none" />

      {/* Header */}
      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-slate-100">
        <nav className="max-w-5xl mx-auto px-6 h-16 flex items-center justify-between">
          <a href="/" className="flex items-center gap-2.5">
            <img src="/uploads/logo.png" style={{ maxWidth: '100%', height: 'auto', width: '140px' }} alt="حياك" />
          </a>
          <button
            onClick={() => navigate('/')}
            className="inline-flex items-center gap-2 text-sm font-bold text-slate-700 bg-white border border-slate-200 rounded-full px-5 py-2 hover:border-teal-300 hover:text-teal-600 shadow-sm transition-all"
          >
            <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" className="rotate-180">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
            الرئيسية
          </button>
        </nav>
      </header>

      {/* Hero */}
      <section className="relative max-w-4xl mx-auto px-6 pt-16 pb-12 text-center">
        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
          <span className="inline-block text-xs font-bold text-teal-700 bg-teal-50 border border-teal-200 px-3 py-1 rounded-full">
            المدونة
          </span>
          <h1 className="mt-5 text-4xl sm:text-5xl font-black text-slate-900 leading-tight">
            دليلك لإدارة متجر سلة بذكاء
          </h1>
          <p className="mt-4 text-base sm:text-lg text-slate-600 max-w-2xl mx-auto leading-loose">
            مقالات عملية، نصائح من خبراء التجارة الإلكترونية، وأحدث استراتيجيات
            البوت الذكي لزيادة مبيعاتك في السوق السعودي.
          </p>
        </motion.div>
      </section>

      {/* Posts grid */}
      <section className="relative max-w-5xl mx-auto px-6 pb-20">
        {POSTS.length === 0 ? (
          <div className="text-center text-slate-500 py-20">
            <p>قريباً — أول مقالاتنا في الطريق.</p>
          </div>
        ) : (
          <div className="grid sm:grid-cols-2 gap-6">
            {POSTS.map((post, i) => (
              <motion.article
                key={post.slug}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: i * 0.06 }}
                className="bg-white border border-slate-200 rounded-2xl overflow-hidden hover:border-teal-300 hover:shadow-soft transition-all group cursor-pointer"
                onClick={() => navigate(`/blog/${post.slug}`)}
              >
                <div className="p-6 sm:p-7">
                  <div className="flex items-center gap-3 text-xs text-slate-500 mb-3">
                    <time dateTime={post.date}>{formatDate(post.date)}</time>
                    <span>•</span>
                    <span>{post.readTime} د قراءة</span>
                  </div>
                  <h2 className="text-xl sm:text-2xl font-black text-slate-900 leading-snug group-hover:text-teal-700 transition-colors">
                    {post.title}
                  </h2>
                  <p className="mt-3 text-sm sm:text-base text-slate-600 leading-loose line-clamp-3">
                    {post.description}
                  </p>
                  <div className="mt-5 flex flex-wrap gap-2">
                    {post.tags.map(tag => (
                      <span key={tag} className="text-xs font-bold text-teal-700 bg-teal-50 border border-teal-100 px-2.5 py-1 rounded-full">
                        {tag}
                      </span>
                    ))}
                  </div>
                  <div className="mt-5 inline-flex items-center gap-1.5 text-sm font-bold text-teal-600 group-hover:gap-3 transition-all">
                    اقرأ المقال
                    <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" className="rotate-180">
                      <path d="M5 12h14M12 5l7 7-7 7" />
                    </svg>
                  </div>
                </div>
              </motion.article>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
