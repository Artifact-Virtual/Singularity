import { useState, useRef, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard,
  Code2,
  Users,
  UserCog,
  DollarSign,
  Building2,
  Server,
  Shield,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  LogOut,
  Bell,
  Search,
  Moon,
  Sun,
  Plug,
  Workflow,
  Zap,
  Settings,
  X,
  Check,
  Info,
  AlertTriangle,
  AlertCircle,
  CheckCircle,
} from 'lucide-react';
import { cn } from '@shared/utils';
import { useTheme } from '@core/providers';
import { useAuth } from '@core/providers';
import { useNotificationStore, type Notification } from '@core/services/notificationStore';
import type { ReactNode } from 'react';

type NavItem = {
  name: string;
  href: string;
  icon: typeof LayoutDashboard;
  children?: NavItem[];
};

const navigation: NavItem[] = [
  { name: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },
  { name: 'Singularity', href: '/ai', icon: Zap },
  {
    name: 'Development',
    href: '/development',
    icon: Code2,
    children: [
      { name: 'Projects', href: '/development/projects', icon: Code2 },
      { name: 'Repositories', href: '/development/repositories', icon: Code2 },
      { name: 'Pipelines', href: '/development/pipelines', icon: Code2 },
      { name: 'Deployments', href: '/development/deployments', icon: Code2 },
    ],
  },
  {
    name: 'CRM',
    href: '/crm',
    icon: Users,
    children: [
      { name: 'Contacts', href: '/crm/contacts', icon: Users },
      { name: 'Deals', href: '/crm/deals', icon: Users },
      { name: 'Campaigns', href: '/crm/campaigns', icon: Users },
      { name: 'Support', href: '/crm/support', icon: Users },
    ],
  },
  {
    name: 'HRM',
    href: '/hrm',
    icon: UserCog,
    children: [
      { name: 'Employees', href: '/hrm/employees', icon: UserCog },
      { name: 'Recruitment', href: '/hrm/recruitment', icon: UserCog },
      { name: 'Performance', href: '/hrm/performance', icon: UserCog },
      { name: 'Payroll', href: '/hrm/payroll', icon: UserCog },
    ],
  },
  {
    name: 'Finance',
    href: '/finance',
    icon: DollarSign,
    children: [
      { name: 'Ledger', href: '/finance/ledger', icon: DollarSign },
      { name: 'Receivables', href: '/finance/receivables', icon: DollarSign },
      { name: 'Payables', href: '/finance/payables', icon: DollarSign },
      { name: 'Reports', href: '/finance/reports', icon: DollarSign },
    ],
  },
  {
    name: 'Stakeholders',
    href: '/stakeholders',
    icon: Building2,
    children: [
      { name: 'Investors', href: '/stakeholders/investors', icon: Building2 },
      { name: 'Board', href: '/stakeholders/board', icon: Building2 },
      { name: 'Partners', href: '/stakeholders/partners', icon: Building2 },
    ],
  },
  {
    name: 'Infrastructure',
    href: '/infrastructure',
    icon: Server,
    children: [
      { name: 'Servers', href: '/infrastructure/servers', icon: Server },
      { name: 'Services', href: '/infrastructure/services', icon: Server },
      { name: 'Monitoring', href: '/infrastructure/monitoring', icon: Server },
    ],
  },
  {
    name: 'Security',
    href: '/security',
    icon: Shield,
    children: [
      { name: 'Users', href: '/security/users', icon: Shield },
      { name: 'Roles', href: '/security/roles', icon: Shield },
      { name: 'Audit', href: '/security/audit', icon: Shield },
    ],
  },
  {
    name: 'Analytics',
    href: '/analytics',
    icon: BarChart3,
    children: [
      { name: 'Dashboards', href: '/analytics/dashboards', icon: BarChart3 },
      { name: 'Reports', href: '/analytics/reports', icon: BarChart3 },
      { name: 'KPIs', href: '/analytics/kpis', icon: BarChart3 },
    ],
  },
  {
    name: 'Integrations',
    href: '/integrations',
    icon: Plug,
  },
  {
    name: 'Workflows',
    href: '/workflows',
    icon: Workflow,
  },
  {
    name: 'Admin',
    href: '/admin',
    icon: Settings,
    children: [
      { name: 'Users', href: '/admin', icon: Settings },
      { name: 'Roles', href: '/admin/roles', icon: Settings },
    ],
  },
];

// Searchable pages for global search
const searchablePages = [
  { name: 'Dashboard', href: '/dashboard', keywords: 'home overview stats' },
  { name: 'Singularity AI', href: '/ai', keywords: 'chat ai assistant bot' },
  { name: 'Contacts', href: '/crm', keywords: 'crm contacts clients customers' },
  { name: 'Deals', href: '/crm/deals', keywords: 'deals pipeline sales' },
  { name: 'Campaigns', href: '/crm/campaigns', keywords: 'marketing campaigns' },
  { name: 'Support Tickets', href: '/crm/support', keywords: 'tickets support help' },
  { name: 'Employees', href: '/hrm', keywords: 'hrm employees staff team' },
  { name: 'Recruitment', href: '/hrm/recruitment', keywords: 'hiring recruitment jobs' },
  { name: 'Payroll', href: '/hrm/payroll', keywords: 'payroll salary wages' },
  { name: 'Invoices', href: '/finance', keywords: 'invoices billing' },
  { name: 'Finance Reports', href: '/finance/reports', keywords: 'financial reports revenue' },
  { name: 'Projects', href: '/development', keywords: 'projects development code' },
  { name: 'Repositories', href: '/development/repositories', keywords: 'git repos code' },
  { name: 'Pipelines', href: '/development/pipelines', keywords: 'ci cd pipelines deploy' },
  { name: 'Stakeholders', href: '/stakeholders', keywords: 'investors board partners' },
  { name: 'Infrastructure', href: '/infrastructure', keywords: 'servers services monitoring' },
  { name: 'Security', href: '/security', keywords: 'users roles audit security' },
  { name: 'Analytics', href: '/analytics', keywords: 'analytics reports kpis charts' },
  { name: 'Integrations', href: '/integrations', keywords: 'integrations connect api' },
  { name: 'Workflows', href: '/workflows', keywords: 'workflows automation' },
  { name: 'Admin', href: '/admin', keywords: 'admin users roles management settings' },
];

function NotificationIcon({ type }: { type: Notification['type'] }) {
  switch (type) {
    case 'success': return <CheckCircle className="h-4 w-4 text-green-500 flex-shrink-0" />;
    case 'warning': return <AlertTriangle className="h-4 w-4 text-yellow-500 flex-shrink-0" />;
    case 'error': return <AlertCircle className="h-4 w-4 text-red-500 flex-shrink-0" />;
    default: return <Info className="h-4 w-4 text-blue-500 flex-shrink-0" />;
  }
}

function formatTimeAgo(date: Date): string {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

type AppLayoutProps = {
  children: ReactNode;
};

export function AppLayout({ children }: AppLayoutProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [expandedItems, setExpandedItems] = useState<string[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchFocused, setSearchFocused] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { setTheme, resolvedTheme } = useTheme();
  const { user, logout } = useAuth();
  const { notifications, unreadCount, isOpen: notifOpen, togglePanel, closePanel, markAsRead, markAllAsRead, removeNotification } = useNotificationStore();
  const searchRef = useRef<HTMLDivElement>(null);
  const notifRef = useRef<HTMLDivElement>(null);

  // Close panels on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setSearchFocused(false);
      }
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) {
        closePanel();
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [closePanel]);

  const toggleExpanded = (name: string) => {
    setExpandedItems((prev) =>
      prev.includes(name)
        ? prev.filter((item) => item !== name)
        : [...prev, name]
    );
  };

  const isActive = (href: string) => location.pathname.startsWith(href);

  // Search filtering
  const filteredPages = searchQuery.trim()
    ? searchablePages.filter(p =>
        p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        p.keywords.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : [];

  return (
    <div className="flex h-screen bg-background">
      {/* Sidebar */}
      <aside
        className={cn(
          'flex flex-col bg-sidebar border-r border-sidebar-border transition-all duration-300',
          sidebarCollapsed ? 'w-16' : 'w-64'
        )}
      >
        {/* Logo */}
        <div className="flex h-16 items-center justify-between px-4 border-b border-sidebar-border">
          {!sidebarCollapsed && (
            <span className="text-lg font-semibold text-sidebar-foreground flex items-center gap-2">
              <span className="text-primary">⚡</span> SINGULARITY
            </span>
          )}
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="p-2 rounded-md hover:bg-sidebar-accent text-sidebar-foreground"
          >
            {sidebarCollapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <ChevronLeft className="h-4 w-4" />
            )}
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto p-2">
          <ul className="space-y-1">
            {navigation.map((item) => (
              <li key={item.name}>
                {item.children ? (
                  <>
                    <button
                      onClick={() => toggleExpanded(item.name)}
                      className={cn(
                        'flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                        isActive(item.href)
                          ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                          : 'text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground'
                      )}
                    >
                      <item.icon className="h-5 w-5 flex-shrink-0" />
                      {!sidebarCollapsed && (
                        <>
                          <span className="flex-1 text-left">{item.name}</span>
                          <ChevronRight
                            className={cn(
                              'h-4 w-4 transition-transform',
                              expandedItems.includes(item.name) && 'rotate-90'
                            )}
                          />
                        </>
                      )}
                    </button>
                    {!sidebarCollapsed && expandedItems.includes(item.name) && (
                      <ul className="ml-4 mt-1 space-y-1">
                        {item.children.map((child) => (
                          <li key={child.name}>
                            <Link
                              to={child.href}
                              className={cn(
                                'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                                isActive(child.href)
                                  ? 'bg-sidebar-primary text-sidebar-primary-foreground'
                                  : 'text-sidebar-foreground hover:bg-sidebar-accent'
                              )}
                            >
                              {child.name}
                            </Link>
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                ) : (
                  <Link
                    to={item.href}
                    className={cn(
                      'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                      isActive(item.href)
                        ? 'bg-sidebar-primary text-sidebar-primary-foreground'
                        : 'text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground'
                    )}
                  >
                    <item.icon className="h-5 w-5 flex-shrink-0" />
                    {!sidebarCollapsed && <span>{item.name}</span>}
                  </Link>
                )}
              </li>
            ))}
          </ul>
        </nav>

        {/* User section */}
        {!sidebarCollapsed && (
          <div className="border-t border-sidebar-border p-4">
            <div className="flex items-center gap-3">
              <div className="h-8 w-8 rounded-full bg-sidebar-primary flex items-center justify-center text-sidebar-primary-foreground text-sm font-medium">
                {user?.firstName?.[0]}
                {user?.lastName?.[0]}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-sidebar-foreground truncate">
                  {user?.firstName} {user?.lastName}
                </p>
                <p className="text-xs text-sidebar-muted-foreground truncate">
                  {user?.email}
                </p>
              </div>
            </div>
          </div>
        )}
      </aside>

      {/* Main content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Header */}
        <header className="flex h-16 items-center justify-between border-b border-border bg-background px-6">
          <div className="flex items-center gap-4" ref={searchRef}>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                type="search"
                placeholder="Search modules..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onFocus={() => setSearchFocused(true)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && filteredPages.length > 0) {
                    navigate(filteredPages[0].href);
                    setSearchQuery('');
                    setSearchFocused(false);
                  }
                  if (e.key === 'Escape') {
                    setSearchFocused(false);
                    setSearchQuery('');
                  }
                }}
                className="h-9 w-64 rounded-md border border-input bg-background pl-10 pr-4 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
              {/* Search results dropdown */}
              {searchFocused && filteredPages.length > 0 && (
                <div className="absolute top-full left-0 mt-1 w-80 rounded-md border border-border bg-popover shadow-lg z-50">
                  {filteredPages.map((page) => (
                    <button
                      key={page.href}
                      onClick={() => {
                        navigate(page.href);
                        setSearchQuery('');
                        setSearchFocused(false);
                      }}
                      className="flex items-center gap-3 w-full px-4 py-2.5 text-sm text-left hover:bg-accent text-foreground first:rounded-t-md last:rounded-b-md"
                    >
                      <Search className="h-3.5 w-3.5 text-muted-foreground" />
                      {page.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Dark mode toggle */}
            <button
              onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
              className="p-2 rounded-md hover:bg-accent text-foreground"
              title={resolvedTheme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {resolvedTheme === 'dark' ? (
                <Sun className="h-5 w-5" />
              ) : (
                <Moon className="h-5 w-5" />
              )}
            </button>

            {/* Notifications */}
            <div className="relative" ref={notifRef}>
              <button
                onClick={togglePanel}
                className="p-2 rounded-md hover:bg-accent text-foreground relative"
                title="Notifications"
              >
                <Bell className="h-5 w-5" />
                {unreadCount > 0 && (
                  <span className="absolute top-1 right-1 flex h-4 w-4 items-center justify-center rounded-full bg-destructive text-[10px] font-bold text-destructive-foreground">
                    {unreadCount > 9 ? '9+' : unreadCount}
                  </span>
                )}
              </button>

              {/* Notification panel */}
              {notifOpen && (
                <div className="absolute right-0 top-full mt-1 w-96 rounded-lg border border-border bg-popover shadow-xl z-50">
                  <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                    <h3 className="font-semibold text-foreground">Notifications</h3>
                    <div className="flex items-center gap-2">
                      {unreadCount > 0 && (
                        <button
                          onClick={markAllAsRead}
                          className="text-xs text-primary hover:underline"
                        >
                          Mark all read
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="max-h-96 overflow-y-auto">
                    {notifications.length === 0 ? (
                      <div className="px-4 py-8 text-center text-muted-foreground text-sm">
                        No notifications
                      </div>
                    ) : (
                      notifications.slice(0, 20).map((notif) => (
                        <div
                          key={notif.id}
                          className={cn(
                            'flex items-start gap-3 px-4 py-3 border-b border-border last:border-0 hover:bg-accent/50 cursor-pointer transition-colors',
                            !notif.read && 'bg-primary/5'
                          )}
                          onClick={() => {
                            markAsRead(notif.id);
                            if (notif.href) {
                              navigate(notif.href);
                              closePanel();
                            }
                          }}
                        >
                          <NotificationIcon type={notif.type} />
                          <div className="flex-1 min-w-0">
                            <p className={cn('text-sm', !notif.read ? 'font-semibold text-foreground' : 'text-foreground')}>
                              {notif.title}
                            </p>
                            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                              {notif.message}
                            </p>
                            <p className="text-xs text-muted-foreground mt-1">
                              {formatTimeAgo(notif.timestamp)}
                            </p>
                          </div>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              removeNotification(notif.id);
                            }}
                            className="p-1 rounded hover:bg-accent text-muted-foreground"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Logout */}
            <button
              onClick={logout}
              className="p-2 rounded-md hover:bg-accent text-foreground"
              title="Sign out"
            >
              <LogOut className="h-5 w-5" />
            </button>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
