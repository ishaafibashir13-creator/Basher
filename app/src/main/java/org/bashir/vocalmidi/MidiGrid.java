package org.bashir.vocalmidi;

/** MIDI quarter-note coordinates are zero-based; the editor displays beat one at zero. */
final class MidiGrid {
    private final double[][] entries;
    MidiGrid(double[][] values) { entries=values; }
    double seconds(double quarter) {
        int i=0; while(i+1<entries.length&&entries[i+1][0]<=quarter)i++;
        return entries[i][1]+(quarter-entries[i][0])*entries[i][2];
    }
    double quarter(double seconds) {
        int i=0; while(i+1<entries.length&&entries[i+1][1]<=seconds)i++;
        return entries[i][0]+(seconds-entries[i][1])/entries[i][2];
    }
    int changes() { return entries.length-1; }
    double initialBpm() { return 60/entries[0][2]; }
}
