import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, BlogPostAdmin } from '../api'

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Intl.DateTimeFormat('ar-SA', {
      year: 'numeric', month: 'long', day: 'numeric',
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

export default function AdminBlog() {
  const navigate = useNavigate()
  const [posts, setPosts]     = useState<BlogPostAdmin[] | null>(null)
  const [error, setError]     = useState('')
  const [deleting, setDeleting] = useState<number | null>(null)

  useEffect(() => {
    document.title = 'إدارة المدونة | حياك'
    load()
  }, [])

  async function load() {
    try {
      const r = await api.blogListAdmin()
      setPosts(r.posts || [])
    } catch (e: any) {
      setError(e.message || 'تعذّر تحميل المقالات')
    }
  }

  async function onDelete(post: BlogPostAdmin) {
    if (!confirm(`هل أنت متأكد من حذف "${post.title}"؟ لا يمكن التراجع.`)) return
    setDeleting(post.id)
    try {
      await api.blogDelete(post.id)
      setPosts(p => (p || []).filter(x => x.id !== post.id))
    } catch (e: any) {
      alert(e.message || 'فشل الحذف')
    } finally {
      setDeleting(null)
    }
  }

  return (
    <div dir="rtl" className="min-h-screen bg-slate-50 font-sans">
      <header className="bg-white border-b border-slate-200 sticky top-0 z-30">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/admin')}
              className="text-slate-500 hover:text-slate-900 transition-colors"
              title="رجوع للوحة المدير العام"
            >
              <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            </button>
            <h1 className="text-xl font-black text-slate-900">إدارة المدونة</h1>
          </div>
          <button
            onClick={() => navigate('/admin/blog/new')}
            className="inline-flex items-center gap-2 text-sm font-bold text-white bg-teal-600 hover:bg-teal-700 rounded-full px-5 py-2.5 transition-colors"
          >
            <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
            مقال جديد
          </button>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8">
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">{error}</div>
        )}

        {posts === null ? (
          <div className="text-center text-slate-400 py-20">جاري التحميل…</div>
        ) : posts.length === 0 ? (
          <div className="text-center py-20">
            <div className="text-slate-600 text-lg mb-4">لا توجد مقالات بعد</div>
            <button
              onClick={() => navigate('/admin/blog/new')}
              className="text-sm font-bold text-teal-600 hover:underline"
            >
              ابدأ بكتابة أول مقال →
            </button>
          </div>
        ) : (
          <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200 text-slate-600">
                <tr>
                  <th className="text-right px-5 py-3 font-bold">العنوان</th>
                  <th className="text-right px-5 py-3 font-bold w-32">الحالة</th>
                  <th className="text-right px-5 py-3 font-bold w-40">تاريخ النشر</th>
                  <th className="text-right px-5 py-3 font-bold w-32">إجراءات</th>
                </tr>
              </thead>
              <tbody>
                {posts.map(post => (
                  <tr key={post.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/50">
                    <td className="px-5 py-4">
                      <button
                        onClick={() => navigate(`/admin/blog/${post.id}`)}
                        className="text-right font-bold text-slate-900 hover:text-teal-600 transition-colors"
                      >
                        {post.title}
                      </button>
                      <div className="text-xs text-slate-400 mt-1 font-mono dir-ltr">/blog/{post.slug}</div>
                    </td>
                    <td className="px-5 py-4">
                      {post.published ? (
                        <span className="inline-flex items-center gap-1.5 text-xs font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2.5 py-1 rounded-full">
                          <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full" />
                          منشور
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-xs font-bold text-amber-700 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-full">
                          <span className="w-1.5 h-1.5 bg-amber-500 rounded-full" />
                          مسودة
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-4 text-slate-600">{formatDate(post.published_at)}</td>
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => navigate(`/admin/blog/${post.id}`)}
                          className="text-xs font-bold text-slate-600 hover:text-teal-600"
                        >
                          تعديل
                        </button>
                        <span className="text-slate-300">|</span>
                        {post.published && (
                          <>
                            <a
                              href={`/blog/${post.slug}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-xs font-bold text-slate-600 hover:text-teal-600"
                            >
                              معاينة
                            </a>
                            <span className="text-slate-300">|</span>
                          </>
                        )}
                        <button
                          onClick={() => onDelete(post)}
                          disabled={deleting === post.id}
                          className="text-xs font-bold text-red-600 hover:text-red-700 disabled:opacity-50"
                        >
                          {deleting === post.id ? '…' : 'حذف'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  )
}
