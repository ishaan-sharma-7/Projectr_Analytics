return (
  <div className="h-screen flex flex-col bg-neutral-950 text-white">

    {/* ───── HEADER ───── */}
    <header className="h-[64px] border-b border-neutral-800 bg-neutral-900 flex items-center px-6">
      <div className="flex items-center gap-3">
        <div className="w-2 h-2 bg-emerald-400 rounded-full" />
        <h1 className="text-lg font-semibold tracking-tight">
          CampusLens
        </h1>
      </div>

      <div className="ml-auto text-xs text-neutral-400 tracking-wide">
        Real-time housing pressure analysis
      </div>
    </header>

    {/* ───── SEARCH BAR ROW ───── */}
    <div className="border-b border-neutral-800 bg-neutral-900 px-6 py-3">
      <SearchBar
        query={searchQuery}
        onChange={setSearchQuery}
        onSubmit={handleSearch}
        onSelectUniversity={handleSelectUniversity}
        extraUniversities={Object.values(dynamicUnis)}
        disabled={false}
        compareMode={compareMode}
        compareLoading={!!loadingName}
        onToggleCompare={handleToggleCompare}
        compareGuide={compareGuide}
        rankingMode={rankingMode}
        onToggleRanking={handleToggleRanking}
      />
    </div>

    {/* ───── MAIN APP LAYOUT ───── */}
    <main className="flex flex-1 min-h-0">

      {rankingMode ? (
        <RankingView
          universities={nationalUniversities}
          onSelect={handleRankingSelect}
          onExitRanking={() => setRankingMode(false)}
        />
      ) : (
        <>
          {/* ───── MAP AREA ───── */}
          <div className="flex-1 relative bg-neutral-950">

            <APIProvider apiKey={MAPS_API_KEY}>
              <MapView
                selectedName={selectedName}
                selectedCoords={selectedCoords}
                scoreCache={scoreCache}
                dynamicUnis={dynamicUnis}
                activeHexData={activeHexData}
                hexRadiusMiles={hexRadiusMiles}
                onHexRadiusChange={setHexRadiusMiles}
                onPinClick={handleSelectUniversity}
                onZoomOut={handleZoomOutMap}
                onZoomChange={setMapZoom}
                onHoverPrefetch={handleHoverPrefetch}
              />
            </APIProvider>

            {/* Empty state hint */}
            {!selectedName && (
              <div className="absolute bottom-4 left-4 text-xs text-neutral-400 bg-neutral-900/70 backdrop-blur px-3 py-1.5 rounded-md border border-neutral-800">
                Search or click a university to begin
              </div>
            )}

          </div>

          {/* ───── SIDE PANEL ───── */}
          <aside className="w-[420px] border-l border-neutral-800 bg-neutral-900/80 backdrop-blur flex flex-col shadow-xl">

            {showCompareResult ? (
              <ComparePanel
                scoreA={compareScoreA!}
                scoreB={compareScoreB!}
                onClear={handleClearCompare}
              />
            ) : compareMode ? (
              <CompareSetupPanel
                compareNames={compareNames}
                scoreCache={scoreCache}
                loadingName={loadingName}
                queuedNames={queuedJobs.map(j => j.name)}
                activeLogs={activeJob?.logs ?? []}
              />
            ) : (
              <SidePanel
                selectedName={selectedName}
                activeScore={activeScore}
                activeJob={activeJob}
                queuedJobs={queuedJobs}
                doneJobs={doneJobs}
                errorJobs={errorJobs}
                onRecompute={handleRecompute}
                onGenerateReport={handleGenerateReport}
                onDismissJob={dismissJob}
                onViewReport={handleViewReport}
                onSelectNearest={handleSelectUniversity}
                extraUniversities={Object.values(dynamicUnis)}
              />
            )}

          </aside>
        </>
      )}
    </main>
  </div>
);
