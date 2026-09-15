-- SPDX-License-Identifier: MIT
-- Copyright (C) 2026 Leonardo Capossio - bard0 design
-- Author: Leonardo Capossio - bard0 design - hello@bard0.com
-- Layer 2b property harness for `counter`, VHDL side. Same three properties as
-- counter_props.sv, written in PSL (read via the ghdl-yosys-plugin with -fpsl):
--
--   1. reset dominates            2. enable counts by one            3. else hold
--
-- Structure mirrors the SV harness: wrap the unmodified DUT, register the
-- previous cycle's inputs/outputs (PSL has no $past), and state the properties
-- over that registered history.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity counter_props is
    generic (
        WIDTH : integer := 8
    );
    port (
        clk : in std_logic;
        rst : in std_logic;
        en  : in std_logic
    );
end entity counter_props;

architecture psl of counter_props is
    signal count      : std_logic_vector(WIDTH-1 downto 0);
    signal prev_count : std_logic_vector(WIDTH-1 downto 0) := (others => '0');
    signal prev_rst   : std_logic := '0';
    signal prev_en    : std_logic := '0';
    signal past_valid : std_logic := '0';
begin
    dut : entity work.counter
        generic map (WIDTH => WIDTH)
        port map (clk => clk, rst => rst, en => en, count => count);

    history : process (clk) is
    begin
        if rising_edge(clk) then
            prev_count <= count;
            prev_rst   <= rst;
            prev_en    <= en;
            past_valid <= '1';
        end if;
    end process history;

    -- psl default clock is rising_edge(clk);
    -- psl assert always ((past_valid = '1' and prev_rst = '1') ->
    --                    (unsigned(count) = 0));
    -- psl assert always ((past_valid = '1' and prev_rst = '0' and prev_en = '1') ->
    --                    (unsigned(count) = unsigned(prev_count) + 1));
    -- psl assert always ((past_valid = '1' and prev_rst = '0' and prev_en = '0') ->
    --                    (unsigned(count) = unsigned(prev_count)));
end architecture psl;
