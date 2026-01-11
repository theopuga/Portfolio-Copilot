import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Dashboard } from './components/pages/Dashboard';
import { ProfilePage } from './components/pages/ProfilePage';
import { PortfolioPage } from './components/pages/PortfolioPage';
import { RecommendationsPage } from './components/pages/RecommendationsPage';
import { HistoryPage } from './components/pages/HistoryPage';
import { ComparePage } from './components/pages/ComparePage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="portfolio" element={<PortfolioPage />} />
          <Route path="recommendations" element={<RecommendationsPage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="compare" element={<ComparePage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
