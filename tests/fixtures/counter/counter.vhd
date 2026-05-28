-- SPDX-License-Identifier: LGPL-2.1-or-later
-- Copyright (C) 2026 Leonardo Capossio - bard0 design
-- VHDL reference equivalent of counter_gold.v, used for the cross-language
-- self-test. Port names match the Verilog (clk/rst/en/count) so formal SEC
-- needs no interface wrapper.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity counter is
    generic (
        WIDTH : integer := 8
    );
    port (
        clk   : in  std_logic;
        rst   : in  std_logic;
        en    : in  std_logic;
        count : out std_logic_vector(WIDTH-1 downto 0)
    );
end entity counter;

architecture rtl of counter is
    signal cnt : unsigned(WIDTH-1 downto 0) := (others => '0');
begin
    process (clk) is
    begin
        if rising_edge(clk) then
            if rst = '1' then
                cnt <= (others => '0');
            elsif en = '1' then
                cnt <= cnt + 1;
            end if;
        end if;
    end process;

    count <= std_logic_vector(cnt);
end architecture rtl;
