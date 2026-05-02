import { Bell } from 'lucide-react'

import { useAuthStore } from '../auth/store'
import { useFirmInfo } from '../firm/useFirmInfo'
import { cn } from '../lib/cn'

import { SSEStatusIndicator } from './SSEStatusIndicator'
import { UserMenu } from './UserMenu'

// Top utility bar per chunk plan §scope_in:
// "top utility bar (firm logo, user menu with logout, notification badge
//  showing 0, SSE status indicator)".

export function TopBar() {
  const user = useAuthStore((s) => s.user)
  const firm = useFirmInfo()
  if (!user) return null

  return (
    <header
      className={cn(
        'h-14 border-b border-gray-200 bg-white flex items-center px-4 gap-4',
      )}
    >
      <FirmLogo logoUrl={firm.data?.branding.logo_url} />
      <div className="flex-1" />
      <NotificationBadge count={0} />
      <SSEStatusIndicator />
      <UserMenu user={user} />
    </header>
  )
}

function FirmLogo({ logoUrl }: { logoUrl: string | undefined }) {
  if (logoUrl) {
    return (
      <img
        src={logoUrl}
        alt="Firm logo"
        className="h-8 w-auto"
        // If the demo logo file isn't deployed at /static/demo-logo.png,
        // fail gracefully to the text fallback so the layout holds.
        onError={(event) => {
          ;(event.currentTarget as HTMLImageElement).style.display = 'none'
        }}
      />
    )
  }
  return (
    <span className="font-semibold text-gray-900 tracking-tight">
      Samriddhi AI
    </span>
  )
}

function NotificationBadge({ count }: { count: number }) {
  return (
    <button
      type="button"
      aria-label={`Notifications (${count})`}
      className={cn(
        'relative w-9 h-9 rounded-md flex items-center justify-center',
        'text-gray-600 hover:bg-gray-100 transition-colors',
      )}
      title="Notifications"
    >
      <Bell size={18} aria-hidden="true" />
      {count > 0 && (
        <span
          className="absolute top-1.5 right-1.5 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-white text-[10px] font-medium flex items-center justify-center"
          aria-hidden="true"
        >
          {count}
        </span>
      )}
    </button>
  )
}
