import { Outlet, NavLink } from 'react-router-dom';
import { LayoutDashboard, User, Briefcase, Lightbulb, History, GitCompare } from 'lucide-react';
import { ProfileIdInput } from './ProfileIdInput';

export function Layout() {
  const navItems = [
    { path: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
    { path: '/profile', icon: User, label: 'Profile' },
    { path: '/portfolio', icon: Briefcase, label: 'Portfolio' },
    { path: '/recommendations', icon: Lightbulb, label: 'Recommendations' },
    { path: '/history', icon: History, label: 'History' },
    { path: '/compare', icon: GitCompare, label: 'Compare' },
  ];

  return (
    <div className="min-h-screen bg-gray-50 flex">
      {/* Sidebar */}
      <aside className="w-64 bg-white border-r border-gray-200 flex flex-col">
        {/* Logo */}
        <div className="h-16 flex items-center px-6 border-b border-gray-200">
          <h1 className="text-xl font-semibold text-gray-900">Portfolio Copilot</h1>
        </div>

        {/* Profile ID Input */}
        <ProfileIdInput />

        {/* Navigation */}
        <nav className="flex-1 px-3 py-4 space-y-1">
          {navItems.map(({ path, icon: Icon, label }) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                  isActive
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-gray-700 hover:bg-gray-100'
                }`
              }
            >
              <Icon className="w-5 h-5" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        {/* Footer Disclaimer */}
        <div className="px-6 py-4 border-t border-gray-200">
          <p className="text-xs text-gray-500">
            Decision-support only. Not investment advice.
          </p>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-auto">
        <div className="max-w-7xl mx-auto p-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
